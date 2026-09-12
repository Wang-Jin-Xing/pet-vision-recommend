"""多 Agent 工作流在节点之间共享的状态结构。

使用 TypedDict：每个节点只更新自己负责的字段，LangGraph 会自动把
节点返回的 dict 合并进全局状态。
"""
from typing import List, Optional, TypedDict


class WorkflowState(TypedDict, total=False):
    # ---- 输入 ----
    user_id: Optional[int]        # 当前登录用户 ID（未登录场景为 None）
    question: str                 # 用户原始问题

    # ---- Supervisor（意图路由）----
    # knowledge 养宠知识 / shopping 商品推荐 / order 订单与配送
    intent: str

    # ---- Knowledge Agent（RAG）----
    context: List[str]            # 知识库检索到的资料片段

    # ---- Shopping Agent（商品推荐）----
    # [{"id","name","price","category","suitable","stock","tags"}]
    product_results: List[dict]
    recommend_keyword: str        # 实际用于推荐检索的关键词

    # ---- Order Agent（下单核算）----
    # [{"product_id","name","quantity","unit_price","subtotal","available"}]
    order_lines: List[dict]
    total: float                  # 订单合计金额
    delivery_info: dict           # 配送评估结果
    current_time: str             # 下单/咨询时间

    # ---- Analysis（安全分析）----
    needs_review: bool            # 是否触发人工审核
    review_reasons: List[str]     # 触发审核的原因

    # ---- Human Review（人工审核）----
    # interrupt() 恢复后写入：approved 确认 / rejected 驳回
    review_decision: Optional[str]

    # ---- Writer（最终回答）----
    answer: str
