"""大模型封装：懒加载 ChatOpenAI，提供意图分类与回答生成能力。

设计原则：
- 未配置 LLM_API_KEY 或调用失败时，返回 None 让上层走本地确定性逻辑降级，
  保证应用在无网络/无 key 时仍可完整运行。
- 所有 LLM 调用都有 try/except + 日志，不向调用方抛出异常。
"""
import json
import logging
from typing import List, Optional

from config import settings

logger = logging.getLogger("petpals.llm")

_llm = None


def get_llm():
    """懒加载 ChatOpenAI 实例（兼容 OpenAI 协议的网关，如智谱 GLM / DeepSeek）。"""
    global _llm
    if _llm is not None:
        return _llm
    if not settings.LLM_API_KEY:
        logger.info("未配置 LLM_API_KEY，AI 工作流将使用本地确定性逻辑")
        return None
    try:
        from langchain_openai import ChatOpenAI

        _llm = ChatOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
        )
        return _llm
    except Exception as e:  # noqa: BLE001
        logger.error("LLM 初始化失败，降级为本地确定性逻辑：%s", e)
        return None


# ------------------------------------------------------------------
# 意图分类
# ------------------------------------------------------------------
_INTENT_PROMPT = """你是宠物电商 PetPals 的智能助手意图分类器。
根据用户问题，判断意图并只输出一个 JSON：{{"intent": "knowledge"|"shopping"|"order"}}

- knowledge：养宠知识咨询（疫苗、驱虫、喂养、疾病症状、护理等）
- shopping：商品浏览/推荐/比价（想看看商品、哪款好、多少钱）
- order：下单/结算/配送/物流/运费/发货时效等订单相关

用户问题：{question}

只输出 JSON，不要解释。"""


def classify_intent(question: str) -> Optional[str]:
    """用 LLM 分类用户意图，失败返回 None（由调用方降级到关键词逻辑）。"""
    llm = get_llm()
    if llm is None:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = llm.invoke(
            [
                SystemMessage(
                    content="你是严谨的意图分类器，只输出 JSON，不输出任何其他文字。"
                ),
                HumanMessage(content=_INTENT_PROMPT.format(question=question)),
            ]
        )
        text = (resp.content or "").strip()
        # 兼容模型偶尔附带 ```json 代码块的情况
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        text = text.strip()
        data = json.loads(text)
        intent = str(data.get("intent", "")).lower()
        if intent in ("knowledge", "shopping", "order"):
            return intent
        logger.warning("LLM 意图分类返回非法值 %r，降级关键词逻辑", intent)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 意图分类失败，降级关键词逻辑：%s", e)
        return None


# ------------------------------------------------------------------
# RAG 回答生成（基于检索到的知识片段合成自然语言回答）
# ------------------------------------------------------------------
_KNOWLEDGE_PROMPT = """你是 PetPals 宠物生活服务平台的养宠顾问。请基于下方「参考资料」回答用户的问题。

要求：
1. 只依据参考资料作答，资料中没有的内容不要编造；
2. 用 Markdown 输出，结构清晰（分点、加粗关键信息）；
3. 语气专业且亲切，结尾提醒健康相关问题以执业兽医意见为准；
4. 字数控制在 300 字以内。

用户问题：{question}

参考资料：
{context}
"""


def generate_knowledge_answer(question: str, context: List[str]) -> Optional[str]:
    """基于检索到的知识片段，用 LLM 合成自然语言回答。失败返回 None。"""
    llm = get_llm()
    if llm is None or not context:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        ctx = "\n\n---\n\n".join(
            f"[资料 {i + 1}]\n{c}" for i, c in enumerate(context)
        )
        resp = llm.invoke(
            [
                SystemMessage(content="你是专业的宠物养护顾问，只依据参考资料回答，不编造。"),
                HumanMessage(
                    content=_KNOWLEDGE_PROMPT.format(question=question, context=ctx)
                ),
            ]
        )
        answer = (resp.content or "").strip()
        return answer or None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 知识回答生成失败，降级模板回答：%s", e)
        return None


# ------------------------------------------------------------------
# 商品/订单回答摘要（一句话自然语言总结，附加在结构化表格之后）
# ------------------------------------------------------------------
def generate_summary(text_prompt: str) -> Optional[str]:
    """通用单段摘要生成。失败返回 None。"""
    llm = get_llm()
    if llm is None:
        return None
    try:
        from langchain_core.messages import HumanMessage

        resp = llm.invoke([HumanMessage(content=text_prompt)])
        return (resp.content or "").strip() or None
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 摘要生成失败：%s", e)
        return None
