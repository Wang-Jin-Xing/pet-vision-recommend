"""LangGraph 多 Agent 工作流组装与对外入口。

图结构见 nodes.py 模块说明。编译时挂载 MemorySaver checkpointer，
使人工审核节点的 interrupt() 可以在同一 thread_id 下用
Command(resume=...) 恢复。

对外入口：
- run_chat(question, user_id)     ：一次性运行（无审核通道时自动驳回）
- stream_workflow(...)           ：流式运行，逐节点产出进度 / interrupt / 回答
- resume_workflow(...)           ：人工审核后恢复
"""
import uuid
from typing import Generator, Optional, Tuple

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agents import nodes
from agents.nodes import route_after_analysis, route_by_intent
from agents.state import WorkflowState

# 节点名 -> 前端进度文案
NODE_LABELS = {
    "supervisor": "正在分析你的意图…",
    "knowledge_agent": "正在检索养宠知识库…",
    "shopping_agent": "正在为你挑选商品…",
    "order_agent": "正在核算订单与配送…",
    "analysis": "正在进行安全分析…",
    "human_review": "等待人工审核确认…",
    "writer": "正在组织回答…",
}


def build_graph():
    """构建并编译多 Agent 状态图（挂载内存 checkpointer 支持 interrupt 恢复）。"""
    graph = StateGraph(WorkflowState)

    graph.add_node("supervisor", nodes.supervisor_node)
    graph.add_node("knowledge_agent", nodes.knowledge_agent_node)
    graph.add_node("shopping_agent", nodes.shopping_agent_node)
    graph.add_node("order_agent", nodes.order_agent_node)
    graph.add_node("analysis", nodes.analysis_node)
    graph.add_node("human_review", nodes.human_review_node)
    graph.add_node("writer", nodes.writer_node)

    graph.add_edge(START, "supervisor")
    # Supervisor 按意图路由到三个专职 Agent
    graph.add_conditional_edges(
        "supervisor",
        route_by_intent,
        {
            "knowledge_agent": "knowledge_agent",
            "shopping_agent": "shopping_agent",
            "order_agent": "order_agent",
        },
    )
    # 三个专职 Agent 汇总到安全分析节点
    graph.add_edge("knowledge_agent", "analysis")
    graph.add_edge("shopping_agent", "analysis")
    graph.add_edge("order_agent", "analysis")

    # 安全分析后：需要审核 -> human_review（interrupt 暂停），否则直达 writer
    graph.add_conditional_edges(
        "analysis",
        route_after_analysis,
        {"human_review": "human_review", "writer": "writer"},
    )
    graph.add_edge("human_review", "writer")
    graph.add_edge("writer", END)

    return graph.compile(checkpointer=MemorySaver())


_graph = None


def get_graph():
    """编译后的图单例（checkpointer 保存在进程内存中）。"""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def stream_workflow(
    question: str,
    user_id: Optional[int] = None,
    thread_id: Optional[str] = None,
) -> Generator[Tuple[str, object], None, None]:
    """首次运行工作流（流式）。

    依次产出：
    - ("progress", 节点名)
    - ("interrupt", 审核 payload dict)  命中人工审核时，之后流结束
    - ("answer", 最终 Markdown 字符串)   未触发审核时
    """
    graph = get_graph()
    thread_id = thread_id or f"run-{uuid.uuid4().hex}"

    yield ("thread_id", thread_id)

    for chunk in graph.stream(
        {"question": question, "user_id": user_id},
        config=_config(thread_id),
        stream_mode="updates",
    ):
        if "__interrupt__" in chunk:
            interrupts = chunk["__interrupt__"]
            yield ("interrupt", interrupts[0].value)
            return
        for node_name in chunk:
            yield ("progress", node_name)

    final = graph.get_state(_config(thread_id))
    yield ("answer", final.values.get("answer", ""))


def resume_workflow(
    thread_id: str,
    decision: str,
) -> Generator[Tuple[str, object], None, None]:
    """人工审核后用 Command(resume=...) 恢复同一 thread。

    decision："approved" 或 "rejected"。
    """
    graph = get_graph()
    for chunk in graph.stream(
        Command(resume=decision),
        config=_config(thread_id),
        stream_mode="updates",
    ):
        if "__interrupt__" in chunk:
            # 理论上不会再 interrupt（图中只有一个审核点），保险处理
            yield ("interrupt", chunk["__interrupt__"][0].value)
            return
        for node_name in chunk:
            yield ("progress", node_name)

    final = graph.get_state(_config(thread_id))
    yield ("answer", final.values.get("answer", ""))


def run_chat(
    question: str,
    user_id: Optional[int] = None,
    thread_id: Optional[str] = None,
) -> dict:
    """一次性运行工作流（供 POST /api/chat 使用）。

    - 未触发审核：返回最终 answer；
    - 触发 interrupt：图暂停在 checkpointer 中，返回 review_required=True
      与审核 payload，不做自动恢复；调用方随后用 POST /api/review 传
      thread_id + decision，经 Command(resume=...) 恢复并取得回答。
    """
    thread_id = thread_id or f"run-{uuid.uuid4().hex}"
    cfg = _config(thread_id)

    review_payload = None
    for event, data in stream_workflow(question, user_id=user_id, thread_id=thread_id):
        if event == "interrupt":
            review_payload = data

    if review_payload is not None:
        return {
            "answer": "",
            "context": [],
            "review_required": True,
            "review": review_payload,
            "thread_id": thread_id,
        }

    values = get_graph().get_state(cfg).values
    return {
        "answer": values.get("answer", ""),
        "context": values.get("context", []),
        "review_required": False,
        "thread_id": thread_id,
        "intent": values.get("intent"),
    }


def has_pending_interrupt(thread_id: str) -> bool:
    """该 thread 是否停在 interrupt 等待恢复（state.next 非空）。"""
    snapshot = get_graph().get_state(_config(thread_id))
    return bool(snapshot.next)


def resume_chat(thread_id: str, decision: str) -> str:
    """人工审核恢复的同步封装：跑完 human_review -> writer，返回最终回答。

    没有待恢复的 interrupt 时抛 RuntimeError，由路由层转成 409。
    """
    if not has_pending_interrupt(thread_id):
        raise RuntimeError("该会话没有待审核的操作")
    answer = ""
    for event, data in resume_workflow(thread_id, decision):
        if event == "answer":
            answer = data or ""
    return answer
