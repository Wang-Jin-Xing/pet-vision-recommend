"""多 Agent 工作流在节点之间共享的状态结构。

使用 TypedDict：每个节点只更新自己负责的字段，LangGraph 会自动把
节点返回的 dict 合并进全局状态。
"""
from typing import List, Optional, TypedDict


class WorkflowState(TypedDict, total=False):
    # ---- 输入 ----
    user_id: Optional[int]        # 当前登录用户 ID（未登录场景为 None）
    question: str                 # 用户原始问题
    # 随消息一起上传的宠物照片（data URL）。为空 = 本次没带图，
    # 此时工作流与加视觉之前**完全一致**（不经过 vision_agent 节点）。
    image_data_url: Optional[str]

    # ---- Vision Agent（视觉识别）----
    pet_profile: Optional[dict]   # 识别出的宠物档案字段（物种/品种/体型/毛发/置信度）
    confidence_grade: str         # 识别置信度档位：high / medium / low

    # ---- Supervisor（意图路由）----
    # knowledge 养宠知识 / shopping 商品推荐 / order 订单与配送
    intent: str

    # ---- Knowledge Agent（RAG）----
    context: List[str]            # 知识库检索到的资料片段

    # ---- Shopping Agent（商品推荐）----
    # [{"id","name","price","category","suitable","species","size","stage","stock","tags"}]
    product_results: List[dict]
    recommend_keyword: str        # 实际用于推荐检索的关键词
    recommend_note: str           # 按宠物档案筛选时的说明（未使用档案时为空）

    # ---- Order Agent（下单核算）----
    # [{"product_id","name","quantity","unit_price","subtotal","available"}]
    order_lines: List[dict]
    total: float                  # 订单合计金额
    delivery_info: dict           # 配送评估结果
    current_time: str             # 下单/咨询时间
    store_info: dict              # 门店营业时间查询结果

    # ---- Analysis（安全分析）----
    needs_review: bool            # 是否触发人工审核
    review_reasons: List[str]     # 触发审核的原因

    # ---- Human Review（人工审核）----
    # interrupt() 恢复后写入：approved 确认 / rejected 驳回
    review_decision: Optional[str]

    # ---- Writer（最终回答）----
    answer: str
