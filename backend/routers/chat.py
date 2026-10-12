"""AI 聊天路由 —— 对接 LangGraph 多 Agent 工作流，全部接口需要登录。

- POST /api/chat         ：发送消息返回回答；用 thread_id 管理会话，
                           触发人工审核时返回 review_required，不自动驳回
- POST /api/chat/stream  ：SSE 流式对话，推送多 Agent 工作进度 /
                           review_required（interrupt 暂停）/ 增量回答
- POST /api/review       ：人工审核确认，用 Command(resume=...) 恢复图，
                           返回最终回答（同时唤醒等待中的 SSE 流）

对话历史（Conversation）以 thread_id 为键并关联 user_id：跨用户访问
一律拒绝。SSE 为单向流，审核桥接见 agents/review.py。
"""
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
import schemas
from agents.graph import (
    NODE_LABELS,
    has_pending_interrupt,
    resume_chat,
    run_chat,
    stream_workflow,
)
from agents.review import review_store
from auth import get_current_user
from database import SessionLocal, get_db
from services import pet_profile as profile_service

logger = logging.getLogger("petvision")

router = APIRouter()
# 审核接口挂在 /api 前缀下（POST /api/review），独立于 /api/chat
review_router = APIRouter()

# 每个工作步骤在前端动画上的最短停留，避免节点执行过快导致进度条闪烁
_PROGRESS_HOLD = 0.25
# 审核通过/驳回后，打字机推送的单块字符数
_DELTA_STEP = 8


def _sse(event: str, data: dict) -> str:
    """构造一条 SSE 报文：event: + data:（单行 JSON），以空行分隔。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _new_thread_id() -> str:
    return uuid.uuid4().hex


def _get_owned_conversation(
    db: Session, thread_id: str, user_id: int
) -> models.Conversation:
    """按 thread_id 查对话并做归属校验；不存在 404，他人会话 403。"""
    conversation = (
        db.query(models.Conversation)
        .filter(models.Conversation.thread_id == thread_id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return conversation


def _get_or_create_conversation(
    db: Session, thread_id: str | None, user_id: int, title: str
) -> models.Conversation:
    """thread_id 为空则新建会话；非空则校验归属后返回。"""
    if thread_id:
        return _get_owned_conversation(db, thread_id, user_id)
    conversation = models.Conversation(
        thread_id=_new_thread_id(),
        user_id=user_id,
        title=title[:20] or "新对话",
    )
    db.add(conversation)
    db.flush()  # 拿到 conversation.id / thread_id 已生成
    return conversation


def _save_user_message(db: Session, conversation_id: int, content: str) -> None:
    db.add(
        models.ChatMessage(
            conversation_id=conversation_id, role="user", content=content
        )
    )
    db.commit()


def _save_assistant_message(db: Session, conversation_id: int, content: str) -> None:
    db.add(
        models.ChatMessage(
            conversation_id=conversation_id, role="assistant", content=content
        )
    )
    db.commit()


def _validate_decision(decision: str) -> str:
    decision = decision.strip().lower()
    if decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=400, detail="decision 仅支持 approved 或 rejected"
        )
    return decision


def _ensure_not_pending(thread_id: str | None) -> None:
    """会话停在人工审核（SSE 审核单或 graph interrupt）时拒绝新消息。"""
    if not thread_id:
        return
    if review_store.is_pending(thread_id) or has_pending_interrupt(thread_id):
        raise HTTPException(
            status_code=409, detail="该会话有正在等待审核的操作，请先完成审核"
        )


# =====================================================================
# POST /api/chat —— 普通一次性问答
# =====================================================================

def _resolve_profile(db: Session, user_id: int, profile_id):
    """取用户选用的宠物档案，转成工作流 state 结构。

    返回 (pet_profile | None, confidence_grade)。
    档案不存在或不属于本人 → 404（不泄露"该 id 存在"）。
    必须在同步阶段完成：SSE 生成器在工作线程跑，不能带上 ORM 会话。
    """
    if not profile_id:
        return None, ""
    prof = profile_service.get_owned_profile(db, user_id, profile_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="宠物档案不存在")
    return profile_service.to_workflow_profile(prof), prof.confidence_grade


@router.post("", response_model=schemas.ChatReply)
def chat(
    payload: schemas.ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """发送消息并返回回答。

    不传 thread_id 自动新建会话；触发人工审核时图在 interrupt 处暂停，
    返回 review_required=True 与审核信息，客户端随后调 POST /api/review。
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    _ensure_not_pending(payload.thread_id)

    # 先解析档案：档案不存在时直接 404，不去创建会话留下空壳
    pet_profile, grade = _resolve_profile(db, current_user.id, payload.pet_profile_id)

    conversation = _get_or_create_conversation(
        db, payload.thread_id, current_user.id, title=message
    )
    _save_user_message(db, conversation.id, message)

    try:
        result = run_chat(
            message,
            user_id=current_user.id,
            thread_id=conversation.thread_id,
            image_data_url=payload.image_data_url,
            pet_profile=pet_profile,
            confidence_grade=grade,
        )
    except Exception:
        # 工作流内部异常不向客户端泄露细节，记录完整堆栈便于排查
        db.rollback()
        logger.exception("非流式聊天工作流执行失败 thread_id=%s", conversation.thread_id)
        raise HTTPException(status_code=500, detail="助手处理失败，请稍后重试")

    if result.get("review_required"):
        # 不保存助手消息；审核恢复时由 POST /api/review 落库
        # interrupt payload 不含 review_id，以会话 thread_id 作为审核单 id
        review_payload = {"review_id": conversation.thread_id, **result["review"]}
        return schemas.ChatReply(
            answer="",
            thread_id=conversation.thread_id,
            review_required=True,
            review=schemas.ReviewInfo(**review_payload),
        )

    _save_assistant_message(db, conversation.id, result["answer"])
    return schemas.ChatReply(
        answer=result["answer"],
        thread_id=conversation.thread_id,
        context=result.get("context", []),
    )


# =====================================================================
# POST /api/chat/stream —— SSE 流式对话
# =====================================================================

@router.post("/stream")
def chat_stream(
    payload: schemas.ChatStreamRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """SSE 流式聊天（所有接口需登录，由 get_current_user 依赖保证）。

    事件流（每条 event:/data: 以空行分隔，data 统一为单行 JSON）：
      thread -> progress* ->
      [review_required -> 阻塞等待 POST /api/review -> progress*] ->
      delta* -> done
    任何阶段失败推送 error 事件。
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    _ensure_not_pending(payload.thread_id)

    # 先解析档案（不存在 → 404，不留空会话）
    pet_profile, grade = _resolve_profile(db, current_user.id, payload.pet_profile_id)

    # 会话校验 / 创建在同步阶段完成，权限错误能返回标准 4xx
    conversation = _get_or_create_conversation(
        db, payload.thread_id, current_user.id, title=message
    )
    _save_user_message(db, conversation.id, message)

    # 在同步阶段取成普通值：StreamingResponse 生成器在工作线程执行，
    # 不能再触碰 commit 后已过期的 ORM 实例
    thread_id = conversation.thread_id
    conversation_id = conversation.id
    user_id = current_user.id
    image_data_url = payload.image_data_url

    def event_stream():
        # 生成器在 anyio 工作线程中迭代，请求级 Session 非线程安全，
        # 这里使用独立 Session 并在 finally 中关闭，确保连接归还连接池
        session = SessionLocal()
        try:
            yield _sse("thread", {"thread_id": thread_id})

            # ---- 首次运行：supervisor -> 专职 Agent -> analysis ----
            review_payload = None
            answer = ""
            for ev, data in stream_workflow(
                message,
                user_id=user_id,
                thread_id=thread_id,
                image_data_url=image_data_url,
                pet_profile=pet_profile,
                confidence_grade=grade,
            ):
                if ev == "progress":
                    yield _sse("progress", {"label": NODE_LABELS.get(data, data)})
                    time.sleep(_PROGRESS_HOLD)
                elif ev == "interrupt":
                    review_payload = data
                elif ev == "answer":
                    answer = data or ""

            # ---- 命中人工审核：发 review_required，等待 /api/review 恢复 ----
            if review_payload is not None:
                review_store.create(
                    message, review_id=thread_id, user_id=user_id
                )
                yield _sse(
                    "review_required",
                    {"review_id": thread_id, "thread_id": thread_id, **review_payload},
                )

                item = review_store.wait(thread_id)

                if item is None and review_store.claim(thread_id, user_id):
                    # 等待超时且没有审核请求抢先：由 SSE 线程以 rejected 恢复
                    try:
                        answer = resume_chat(thread_id, "rejected")
                    except Exception:
                        logger.exception(
                            "审核超时后自动恢复失败 thread_id=%s", thread_id
                        )
                        review_store.discard(thread_id)
                        yield _sse(
                            "error", {"message": "审核恢复失败，请稍后重新发起请求"}
                        )
                        return
                    _save_assistant_message(session, conversation_id, answer)
                    for i in range(0, len(answer), _DELTA_STEP):
                        yield _sse("delta", {"text": answer[i:i + _DELTA_STEP]})
                        time.sleep(0.02)
                    yield _sse("done", {"thread_id": thread_id, "cancelled": True})
                    review_store.discard(thread_id)
                    return

                if item is None:
                    # 与审核请求竞速：它已认领但尚未写回结果，再等一轮
                    item = review_store.wait(thread_id, timeout=30)

                if item is None:
                    yield _sse(
                        "error", {"message": "审核恢复超时，请稍后重新发起请求"}
                    )
                    return

                if item.error:
                    yield _sse("error", {"message": item.error})
                    return

                answer = item.answer or ""
                cancelled = item.decision == "rejected"
                yield _sse(
                    "progress",
                    {"label": "审核已通过，继续处理…" if not cancelled else "已驳回，正在整理结果…"},
                )
                time.sleep(_PROGRESS_HOLD)
                # 助手消息已由 /api/review 落库，这里只负责增量推送
                for i in range(0, len(answer), _DELTA_STEP):
                    yield _sse("delta", {"text": answer[i:i + _DELTA_STEP]})
                    time.sleep(0.02)
                yield _sse("done", {"thread_id": thread_id, "cancelled": cancelled})
                return

            # ---- 无审核：落库 + 打字机增量推送 ----
            _save_assistant_message(session, conversation_id, answer)
            for i in range(0, len(answer), _DELTA_STEP):
                yield _sse("delta", {"text": answer[i:i + _DELTA_STEP]})
                time.sleep(0.02)
            yield _sse("done", {"thread_id": thread_id, "cancelled": False})
        except Exception:
            # 流式阶段无法再改 HTTP 状态码，用 error 事件通知；
            # 内部异常细节仅写日志，不下发给客户端
            logger.exception("SSE 聊天流异常 thread_id=%s", thread_id)
            review_store.discard(thread_id)
            session.rollback()
            yield _sse("error", {"message": "助手处理失败，请稍后重试"})
        finally:
            session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭代理缓冲，保证事件实时下发
        },
    )


# =====================================================================
# POST /api/review —— 人工审核确认，Command(resume=...) 恢复图
# =====================================================================

@review_router.post("/review", response_model=schemas.ReviewResult)
def submit_review(
    payload: schemas.ReviewRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """对 interrupt 暂停的会话提交人工审核决定。

    在线程内用 Command(resume=decision) 恢复 LangGraph（见 resume_chat），
    最终回答随本接口返回；若该会话连着 SSE 流，同时唤醒它继续增量推送。
    """
    thread_id = payload.thread_id.strip()
    decision = _validate_decision(payload.decision)

    conversation = _get_owned_conversation(db, thread_id, current_user.id)

    # 该会话是否有正在阻塞等待的 SSE 流；原子认领，防止重复恢复
    sse_waiting = review_store.is_pending(thread_id)
    if sse_waiting and not review_store.claim(thread_id, current_user.id):
        raise HTTPException(status_code=409, detail="该审核已被处理，请勿重复提交")

    if not has_pending_interrupt(thread_id):
        if sse_waiting:
            review_store.discard(thread_id)
        raise HTTPException(status_code=409, detail="该会话没有待审核的操作（可能已超时失效）")

    try:
        answer = resume_chat(thread_id, decision)
    except RuntimeError:
        # has_pending_interrupt 检查之后被并发请求抢先恢复
        logger.warning("审核恢复时会话已无 interrupt thread_id=%s", thread_id)
        if sse_waiting:
            review_store.discard(thread_id)
        raise HTTPException(status_code=409, detail="该审核已被处理，请勿重复提交")
    except Exception:
        logger.exception("恢复审核工作流失败 thread_id=%s", thread_id)
        if sse_waiting:
            # 透传给 SSE 端的文案同样不包含内部异常细节
            review_store.complete(
                thread_id, decision, error="工作流恢复失败，请稍后重试"
            )
        raise HTTPException(status_code=500, detail="工作流恢复失败，请稍后重试")

    # 审核后的助手回答统一在此落库（流式 / 非流式两条路径都覆盖）
    _save_assistant_message(db, conversation.id, answer)

    if sse_waiting:
        review_store.complete(thread_id, decision, answer=answer)

    return schemas.ReviewResult(
        ok=True, thread_id=thread_id, decision=decision, answer=answer
    )
