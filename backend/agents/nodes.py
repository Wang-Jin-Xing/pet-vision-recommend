"""多 Agent 工作流的节点函数。

拓扑：

    START
      │
      ▼
  supervisor（意图路由）
      │ 条件边
      ├──► knowledge_agent（养宠知识，search_pet_care）
      ├──► shopping_agent （商品推荐，recommend_products）
      └──► order_agent    （下单核算，calculate_total/check_delivery/get_current_time）
                        │
                        ▼
                    analysis（安全分析：金额阈值 / 敏感关键词）
                        │ 条件边
              需要审核 ──┴── 无需审核
                 ▼             │
          human_review          │
          (interrupt 暂停)      │
                 │              │
                 └──────┬───────┘
                        ▼
                     writer（组织最终 Markdown 回答）
                        │
                        ▼
                       END

当前所有 Agent 采用「LLM 优先 + 本地确定性兜底」的混合策略：
- 配置了 LLM_API_KEY 时，意图分类由大模型完成，知识回答由大模型基于
  RAG 检索结果合成；
- 未配置 key 或 LLM 调用失败时，自动回退到关键词路由 + 模板生成，
  保证应用在任何环境下都能完整跑通。
"""
import json
import logging
import re
from typing import List, Optional

from langgraph.types import interrupt

from agents import llm as llm_helper
from agents import vision
from agents.state import WorkflowState
from agents.tools import (
    calculate_total,
    check_delivery,
    get_current_time,
    get_store_hours,          # ← 新加
    list_categories,
    query_products,
    recommend_products,
    search_pet_care,
)
from services.pet_profile import grade_confidence
from services.recommend import filter_by_profile

logger = logging.getLogger("petpals.nodes")

# 意图常量
INTENT_KNOWLEDGE = "knowledge"
INTENT_SHOPPING = "shopping"
INTENT_ORDER = "order"

# 人工审核触发条件
REVIEW_AMOUNT_THRESHOLD = 500.0
SENSITIVE_KEYWORDS = ["退款", "退货", "理赔", "投诉", "取消订单", "删除订单"]

# 意图关键词
# 注意：SENSITIVE_KEYWORDS（人工审核用）里那批操作词，这里必须同时登记一份。
# 否则会出现「安全分析认得出是风险、主管却认不出该走订单流程」的认知不一致，
# 表现为「我要退款」被判成养宠知识、审完还是答非所问。
_ORDER_KEYWORDS = [
    "下单", "订单", "结算", "结账", "买单", "付款", "支付", "发货", "物流",
    "配送", "快递", "收货", "送到", "运费", "多久到", "什么时候到", "买",
    # 与 SENSITIVE_KEYWORDS 对齐：退款 / 退货等属于订单类操作
    "退款", "退货", "理赔", "投诉", "取消订单", "删除订单", "换货","门店", "营业", "几点开门", "几点关门", "营业时间", "地址", "电话", 
]
_SHOPPING_KEYWORDS = [
    "推荐", "有什么", "有哪些", "商品", "价格", "多少钱", "便宜", "选购",
    "想买", "种草", "排行榜", "哪款", "哪个好", "对比", "比较", "几款",
    "几种", "性价比",
]
# 健康/养护强信号：即使句中含「有什么」等宽泛购物词（如
# 「狗狗细小病毒有什么症状」），也应路由到知识检索
_KNOWLEDGE_KEYWORDS = [
    "疫苗", "驱虫", "洗澡", "喂养", "喂食", "饲养", "怎么养", "护理",
    "症状", "生病", "疾病", "疾病信号", "发烧", "发热", "呕吐", "拉稀",
    "腹泻", "软便", "便血", "血便", "咳嗽", "打喷嚏", "精神不好",
    "不吃东西", "传染", "耳螨", "猫癣", "皮肤病", "狂犬", "三联",
    "绝育", "怀孕", "刷牙", "剪指甲", "换粮", "尿闭", "尿不出",
    "注意事项", "知识", "指南", "细小", "犬瘟", "猫瘟", "鼻支",
]
# 配送地区关键词
_REGION_KEYWORDS = [
    "北京", "上海", "广州", "深圳", "天津", "重庆", "江苏", "浙江", "广东",
    "福建", "山东", "河北", "河南", "湖北", "湖南", "四川", "陕西", "安徽",
    "江西", "辽宁", "吉林", "黑龙江", "山西", "广西", "云南", "贵州", "海南",
    "甘肃", "青海", "宁夏", "新疆", "西藏", "内蒙", "同城",
]
# 已收录实体门店的城市（与 tools.py 的 _STORE_HOURS 对应）
_STORE_CITIES = ["北京", "上海", "广州", "深圳", "沧州"]

# 数量单位
_QTY_UNITS = "袋|包|个|件|盒|罐|支|瓶|箱|条|只"
# 中文数字
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# 商品名中的通用修饰词，不作为下单匹配词
_GENERIC_NAME_TOKENS = {
    "营养", "全价", "温和", "专用", "精选", "天然", "优质", "升级", "配方",
    "成犬", "成猫", "幼猫", "幼犬", "深海", "鱼味", "洁齿", "除臭", "结团",
    "羽毛", "味美", "保湿", "清洁", "健康", "美味",
}


def _json(tool, payload: dict) -> dict:
    """调用 @tool 工具并解析其 JSON 字符串结果。"""
    return json.loads(tool.invoke(payload))


# =====================================================================
# Vision Agent：宠物照片识别（可选前置节点）
# =====================================================================

def route_start(state: WorkflowState) -> str:
    """入口条件边：**带了照片**才先进视觉节点，否则直接进 supervisor。

    这条边是「增量挂载」的关键——不带图时走的是与改造前**完全相同**的老路径，
    既有 7 个节点一行没动，所以原有行为不会漂移。
    """
    return "vision_agent" if state.get("image_data_url") else "supervisor"


def vision_agent_node(state: WorkflowState) -> dict:
    """把用户上传的宠物照片识别成结构化档案信息。

    识别结果写入 pet_profile / confidence_grade，供后续两个节点使用：
    - shopping_agent：按档案条件筛商品（**档位不同，筛的条件不同**）
    - analysis      ：低档档案触发人工审核

    识别失败**不阻断流程**：降级成"无档案"，后续按普通咨询处理。
    """
    data_url = state.get("image_data_url") or ""
    try:
        result = vision.classify_data_url(data_url)
    except Exception:  # noqa: BLE001 —— 识别只是增强，绝不能拖垮主流程
        logger.exception("视觉识别异常，按无档案继续")
        result = {
            "species": "未知", "species_code": "other", "size_code": "unknown",
            "confidence": 0.0, "_mode": "vlm_error",
        }

    grade = grade_confidence(
        result.get("confidence", 0.0), result.get("species_code", "other")
    )
    profile = {
        "species": result.get("species", "未知"),
        "species_code": result.get("species_code", "other"),
        "breed": result.get("breed", "未知"),
        "size": result.get("size", "不确定"),
        "size_code": result.get("size_code", "unknown"),
        "body_condition": result.get("body_condition", "——"),
        "coat_condition": result.get("coat_condition", "——"),
        "health_notes": result.get("health_notes", "——"),
        "confidence": result.get("confidence", 0.0),
        "rejected": bool(result.get("rejected")),
        "reject_reason": result.get("reject_reason", ""),
        "mode": result.get("_mode", ""),
    }
    logger.info(
        "视觉识别：物种=%s 体型=%s 置信度=%.2f 档位=%s",
        profile["species"], profile["size"], profile["confidence"], grade,
    )
    return {"pet_profile": profile, "confidence_grade": grade}


# =====================================================================
# Supervisor：意图路由
# =====================================================================

def supervisor_node(state: WorkflowState) -> dict:
    """意图路由：优先用 LLM 分类，失败/无 key 时回退到关键词规则。"""
    q = state.get("question", "")

    intent = llm_helper.classify_intent(q)
    if intent is None:
        if any(k in q for k in _ORDER_KEYWORDS):
            intent = INTENT_ORDER
        elif any(k in q for k in _KNOWLEDGE_KEYWORDS):
            intent = INTENT_KNOWLEDGE
        elif any(k in q for k in _SHOPPING_KEYWORDS):
            intent = INTENT_SHOPPING
        else:
            intent = INTENT_KNOWLEDGE
        logger.info("意图分类（关键词兜底）：%s -> %s", q[:20], intent)
    else:
        logger.info("意图分类（LLM）：%s -> %s", q[:20], intent)

    return {"intent": intent}


def route_by_intent(state: WorkflowState) -> str:
    """Supervisor 之后的条件边。"""
    return {
        INTENT_KNOWLEDGE: "knowledge_agent",
        INTENT_SHOPPING: "shopping_agent",
        INTENT_ORDER: "order_agent",
    }.get(state.get("intent"), "knowledge_agent")


# =====================================================================
# Knowledge Agent：养宠知识检索
# =====================================================================

# 与"问什么"无关的表达：格式指令词 / 客套话 / Markdown 演示意图词。
# 检索前清洗，避免「请用 Markdown 表格整理幼犬疫苗时间表」这类问题
# 把整句原样送进向量库，拉低相关度。
_FORMAT_STOPWORDS = [
    "请你", "请帮我", "帮我", "麻烦", "请问", "请用", "给我", "给一个",
    "一下", "可以", "能不能", "markdown", "Markdown", "表格", "代码块",
    "代码", "示例", "例子", "格式", "输出", "打印", "整理", "列出", "罗列",
    "分别", "包含", "包括", "以及", "如下", "所示", "至少", "不少于",
    "无序列表", "有序列表", "列表", "清单", "列为",
    "Python", "python", "hello", "之后", "最后",
]


def _strip_format_words(text: str) -> str:
    """去掉格式/客套词与标点，留下真正的检索主题。"""
    cleaned = text
    for w in _FORMAT_STOPWORDS:
        cleaned = cleaned.replace(w, " ")
    cleaned = re.sub(r"[，。？?！!、：:；;（）()【】\[\]~～\s]+", " ", cleaned)
    return cleaned.strip()


def knowledge_agent_node(state: WorkflowState) -> dict:
    """调用 search_pet_care 工具做 RAG 检索（用清洗后的主题词提升相关度）。"""
    topic = _strip_format_words(state["question"]) or state["question"]
    result = _json(search_pet_care, {"query": topic, "top_k": 3})
    return {"context": result.get("chunks", [])}


# =====================================================================
# Shopping Agent：商品推荐
# =====================================================================

# 推荐场景下无意义的停用词，用于从问题中提取检索关键词
_SHOPPING_STOPWORDS = _FORMAT_STOPWORDS + [
    "推荐", "有没有", "有什么", "有哪些", "商品", "价格", "多少钱",
    "便宜", "选购", "想买", "种草", "排行榜", "哪款", "哪个好", "适合",
    "家里", "我家", "谢谢", "宝宝", "毛孩子", "对比", "比较", "区别",
    "不同", "差异", "款", "种", "适用年龄", "年龄",
]

# 商品核心词：用户口语 -> 数据库名称/描述模糊词。
# 长词在前，避免「猫粮」抢先匹配掉「幼猫粮」之类的更长表达。
_PRODUCT_CORE_TERMS = [
    "幼犬粮", "幼猫粮", "成犬粮", "成猫粮", "狗粮", "猫粮", "猫砂",
    "沐浴露", "磨牙骨", "逗猫棒", "零食", "罐头", "玩具", "驱虫",
]


def _extract_product_terms(question: str) -> List[str]:
    """识别问题中点名的商品核心词（支持「狗粮和猫粮的区别」多词对比）。"""
    terms, hit_spans = [], []
    for term in _PRODUCT_CORE_TERMS:
        start = question.find(term)
        if start == -1:
            continue
        # 已被更长的词覆盖（如「猫粮」落在「幼猫粮」区间内）则跳过
        if any(s <= start < e for s, e in hit_spans):
            continue
        terms.append(term)
        hit_spans.append((start, start + len(term)))
    return terms


def _extract_desired_count(question: str) -> Optional[int]:
    """解析「3 种 / 三款 / 两款」这类期望返回数量；未指定返回 None。"""
    m = re.search(r"(\d+|[一二两三四五六七八九十])\s*(?:种|款|样)", question)
    if not m:
        return None
    token = m.group(1)
    return int(token) if token.isdigit() else _CN_NUM.get(token)


def _extract_recommend_keyword(question: str) -> str:
    """从自然语言问题中提取商品检索关键词（去掉格式词与推荐停用词）。"""
    text = question
    for w in _SHOPPING_STOPWORDS:
        text = text.replace(w, " ")
    # 去掉标点与多余空白，取剩余的连续片段
    text = re.sub(r"[，。？?！!、~～\s]+", " ", text).strip()
    return text


def shopping_agent_node(state: WorkflowState) -> dict:
    """调用 recommend_products 工具：识别分类 + 提取关键词，实时读库推荐。

    关键词优先级：
    1. 问题中显式点名的商品核心词（可多个，如「狗粮和猫粮对比」分别检索后合并）；
    2. 去除停用词后的整句关键词兜底。
    """
    question = state["question"]

    category = ""
    for cat in list_categories():
        if cat in question:
            category = cat
            break

    want = _extract_desired_count(question)
    limit = max(1, min(want or 6, 10))

    terms = _extract_product_terms(question)
    products: List[dict] = []
    label = "全部商品"
    # 商品分类名（如"玩具/零食"）在商品标题里不一定出现，命中分类时走分类过滤
    categories = list_categories()
    if terms:
        # 多核心词对比：每个词各取一部分配额，按 id 去重合并
        per_term = max(1, limit // len(terms)) if len(terms) > 1 else limit
        seen_ids = set()
        for term in terms:
            if term in categories:
                payload = {"keyword": "", "category": term, "limit": per_term}
            else:
                payload = {"keyword": term, "category": "", "limit": per_term}
            result = _json(recommend_products, payload)
            for p in result.get("products", []):
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    products.append(p)
        label = "、".join(terms)

    if not products:
        # 无核心词或核心词在库中无命中：用去停用词后的整句关键词兜底
        keyword = _extract_recommend_keyword(question)
        # 关键词恰好就是分类名时不再作为名称关键词（如"宠物食品有哪些"）
        if keyword == category:
            keyword = ""
        result = _json(
            recommend_products,
            {"keyword": keyword, "category": category, "limit": limit},
        )
        products = result.get("products", [])
        label = keyword or category or "全部商品"

    products = products[:limit]

    # 本次请求带了宠物照片时（视觉节点已产出档案），按档案条件再筛一次。
    # **档位不同、筛的条件不同**：high 全量条件 / medium 只按物种 / low 完全不筛。
    note = ""
    profile = state.get("pet_profile")
    if profile:
        products, note = filter_by_profile(
            products, profile, state.get("confidence_grade", "")
        )

    return {
        "product_results": products,
        "recommend_keyword": label,
        "recommend_note": note,
    }


# =====================================================================
# Order Agent：解析下单意图 + 价格/配送/时间核算
# =====================================================================

def _extract_quantities(question: str) -> List[int]:
    """提取问题中的数量（阿拉伯数字 + 常见中文数字），按出现顺序返回。"""
    quantities = []
    for m in re.finditer(rf"(\d+|[一二两三四五六七八九十])\s*(?:{_QTY_UNITS})?", question):
        token = m.group(1)
        quantities.append(int(token) if token.isdigit() else _CN_NUM.get(token, 1))
    return quantities


def _parse_order_items(question: str) -> List[dict]:
    """把自然语言下单请求解析为 [{"product_id","quantity"}]。

    支持两种写法：
    1. 显式商品编号，如「下单 #3 两件」「买2号商品」；
    2. 自然语言商品名，如「买两袋狗粮」，用数据库里的真实商品名做子串匹配。
    """
    # 1) 显式 #id 或「N号商品」（数字紧跟"元/块"的金额表达不会误匹配）
    id_matches = [
        m
        for pair in re.findall(r"#(\d+)|(?<!\d)(\d+)\s*号(?:商品|产品)?", question)
        for m in pair
        if m
    ]

    products = query_products(keyword="", limit=50)
    items: List[dict] = []

    if id_matches:
        quantities = _extract_quantities(question)
        for idx, pid_text in enumerate(id_matches):
            qty = quantities[idx] if idx < len(quantities) else 1
            items.append({"product_id": int(pid_text), "quantity": qty})
        return items

    # 2) 商品名子串匹配：取名称中的 2~3 字片段与问题匹配
    #    （中文名无空格分词，用滑窗生成候选，过滤通用修饰词）
    def _candidate_tokens(name: str) -> List[str]:
        core = re.sub(r"[\d.]+\s*(kg|KG|升|L|ml|ML|支装|条装|片装)", "", name)
        grams = set()
        for n in (3, 2):
            for i in range(len(core) - n + 1):
                token = core[i:i + n]
                if re.fullmatch(r"[一-龥]+", token) and token not in _GENERIC_NAME_TOKENS:
                    grams.add(token)
        # 3 字词优先级更高
        return sorted(grams, key=lambda t: -len(t))

    scored = []
    for p in products:
        best = next(
            (t for t in _candidate_tokens(p["name"]) if t in question),
            None,
        )
        if best:
            scored.append((len(best), p))
    # 命中词越长越靠前，同长按商品 id，保证结果稳定
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    matched = [p for _, p in scored]

    if not matched:
        return items

    quantities = _extract_quantities(question)
    # 数量与商品按匹配顺序对齐，未写数量默认 1
    for idx, p in enumerate(matched):
        qty = quantities[idx] if idx < len(quantities) else 1
        items.append({"product_id": p["id"], "quantity": qty})
    return items


def _extract_region(question: str) -> str:
    for region in _REGION_KEYWORDS:
        if region in question:
            return region
    return ""


def order_agent_node(state: WorkflowState) -> dict:
    """解析订单 -> 调用 calculate_total / check_delivery / get_current_time / get_store_hours。"""
    question = state["question"]
    items = _parse_order_items(question)

    lines, total = [], 0.0
    if items:
        pricing = _json(calculate_total, {"items": items})
        lines = pricing.get("lines", [])
        total = float(pricing.get("total", 0.0))

    region = _extract_region(question)
    delivery = _json(check_delivery, {"region": region, "items": items})

    now_info = _json(get_current_time, {})
    current_time = f"{now_info['datetime']}（{now_info['weekday']}）"

    # 门店营业时间：只有当问题里提到"门店/营业/几点/开门/关门/地址/电话"时才查
    store_info = None
    if any(k in question for k in ("门店", "营业", "开门", "关门", "几点", "营业时间", "地址", "电话", "实体店")):
        city = region or (region if region else "")
        # 城市优先从问题里取（region 可能为空）
        for name in _STORE_CITIES:
            if name in question:
                city = name
                break
        store_info = _json(get_store_hours, {"city": city, "date": question})

    update = {
        "order_lines": lines,
        "total": round(total, 2),
        "delivery_info": delivery,
        "current_time": current_time,
    }
    if store_info is not None:
        update["store_info"] = store_info
    # 未解析出商品时给 Writer 一个标记，引导用户补充商品名/编号
    if not items:
        delivery["no_matched_product"] = True
        # 但如果是问门店，就不该提示"缺少商品"
        if store_info is not None:
            delivery.pop("no_matched_product", None)
    return update


# =====================================================================
# Analysis：安全分析（是否需要人工审核）
# =====================================================================

def analysis_node(state: WorkflowState) -> dict:
    """是否需要人工审核。三种触发情况：

    1. 订单金额超过阈值；
    2. 命中敏感操作关键词；
    3. **照片识别置信度过低**。

    第 3 条是本项目新加的：识别不可信时**转人工确认，而不是直接拒掉用户**。
    它复用了同一套 interrupt/resume 机制——图结构一行没改，只是多了一个触发理由。
    """
    reasons: List[str] = []
    question = state.get("question", "")

    total = float(state.get("total", 0.0) or 0.0)
    if state.get("intent") == INTENT_ORDER and total > REVIEW_AMOUNT_THRESHOLD:
        reasons.append(
            f"订单金额 ¥{total:.2f} 超过 ¥{REVIEW_AMOUNT_THRESHOLD:.0f} 审核阈值"
        )

    hit = [k for k in SENSITIVE_KEYWORDS if k in question]
    if hit:
        reasons.append("包含敏感操作关键词：" + "、".join(hit))

    # 第三条：低置信识别结果 → 转人工确认（把 HITL 从「风控」用成「降级兜底」）
    profile = state.get("pet_profile")
    if profile and state.get("confidence_grade") == "low":
        conf = float(profile.get("confidence", 0.0) or 0.0)
        reasons.append(f"照片识别置信度较低（{conf:.0%}），需人工确认识别结果")

    return {"needs_review": bool(reasons), "review_reasons": reasons}


def route_after_analysis(state: WorkflowState) -> str:
    """Analysis 之后的条件边。"""
    return "human_review" if state.get("needs_review") else "writer"


# =====================================================================
# Human Review：interrupt 人工审核节点
# =====================================================================

def human_review_node(state: WorkflowState) -> dict:
    """调用 interrupt() 暂停工作流，等待前端确认/驳回；恢复值写入 review_decision。"""
    intent_label = {
        INTENT_ORDER: "订单操作",
        INTENT_SHOPPING: "商品相关操作",
        INTENT_KNOWLEDGE: "敏感请求",
    }.get(state.get("intent"), "操作")

    payload = {
        "title": "该操作需要人工审核",
        "action": intent_label,
        "question": state.get("question", ""),
        "total": float(state.get("total", 0.0) or 0.0),
        "reasons": state.get("review_reasons", []),
        "current_time": state.get("current_time", ""),
        # 因识别问题触发审核时，把识别结果一并带给审核人看
        "pet_profile": state.get("pet_profile"),
        "confidence_grade": state.get("confidence_grade", ""),
        "description": (
            "该请求触发了人工审核规则，请确认是否继续："
            + "；".join(state.get("review_reasons", []))
        ),
    }

    # interrupt：图在此暂停；恢复时 Command(resume="approved"/"rejected")
    # 的值作为 interrupt() 的返回值
    decision = interrupt(payload)
    decision = str(decision).strip().lower()
    if decision not in ("approved", "rejected"):
        decision = "rejected"
    return {"review_decision": decision}


# =====================================================================
# Writer：组织最终 Markdown 回答
# =====================================================================

def _write_knowledge(state: WorkflowState) -> str:
    question = state["question"]
    chunks = state.get("context", [])
    if chunks:
        topic = _strip_format_words(question) or question
        # 优先用 LLM 基于检索片段合成自然语言回答（真正的 RAG）
        ai_answer = llm_helper.generate_knowledge_answer(question, chunks)
        if ai_answer:
            parts = [
                f"### 🐾 关于「{topic}」的解答\n",
                ai_answer,
                "\n\n---\n\n**📚 参考资料来源：**\n",
            ]
            for i, chunk in enumerate(chunks, 1):
                preview = chunk.strip().replace("\n", " ")
                if len(preview) > 60:
                    preview = preview[:60] + "…"
                parts.append(f"{i}. {preview}")
            return "\n".join(parts)

        # LLM 不可用时回退：直接呈现资料正文
        parts = [
            "### 🐾 为你整理的养宠参考资料\n",
            f"围绕「**{topic}**」，我从知识库中找到 **{len(chunks)}** 条相关资料：\n",
        ]
        for i, chunk in enumerate(chunks, 1):
            body = chunk.strip()
            parts.append(f"#### 📄 资料 {i}\n\n{body}\n")
        parts.append(
            "**阅读建议：**\n\n"
            "1. 优先参考与自家宠物年龄、品种最接近的内容\n"
            "2. 涉及疫苗、驱虫、疾病等健康问题时，请以执业兽医意见为准\n\n"
            "> 以上内容来自已上传资料，仅供日常参考。"
        )
        return "\n".join(parts)
    return (
        "### 你好，我是 PetPals 智能助手\n\n"
        f"知识库中暂时没有检索到与「**{question}**」直接相关的资料。你可以：\n\n"
        "1. 在聊天页左侧上传 **txt / md** 格式的养宠资料，我会基于文档回答\n"
        "2. 换一个更具体的关键词再试一次\n\n"
        "**热门问题：**\n\n"
        "- 幼猫到家需要准备哪些物品？\n"
        "- 狗粮和猫粮的营养配比有什么区别？\n"
        "- 宠物多久洗一次澡比较合适？\n"
        "- 狗狗疫苗的接种时间怎么安排？\n"
    )


_COMPARE_HINTS = ("对比", "比较", "区别", "差异", "哪个好", "哪款好", "vs", "VS")


def _wants_code_sample(question: str) -> bool:
    """用户显式要求代码块/代码示例时才附加，避免普通推荐回答变冗长。"""
    return "代码" in question


def _code_sample_appendix(products: List[dict]) -> str:
    """用检索到的真实商品生成一段 Python 价格计算示例。"""
    samples = products[:2] or [
        {"name": "示例商品", "price": 99.0}
    ]
    lines = [
        'products = [',
        *[
            f'    {{"name": "{p["name"]}", "price": {p["price"]:.1f}}},'
            for p in samples
        ],
        ']',
        '',
        'for p in products:',
        '    print(f"{p["name"]}：¥{p["price"]:.2f}")',
        'print(f"共 {len(products)} 种商品")',
    ]
    code = "\n".join(lines)
    return (
        "\n\n**🧑‍💻 代码示例（Python 遍历商品价格）：**\n\n"
        f"```python\n{code}\n```"
    )


def _write_shopping(state: WorkflowState) -> str:
    products = state.get("product_results", [])
    keyword = state.get("recommend_keyword", "全部商品")
    decision = state.get("review_decision")
    question = state["question"]

    if decision == "rejected":
        return (
            "### 操作已驳回\n\n"
            f"你请求的商品相关操作「**{question}**」已被取消，"
            "我不会继续执行。\n\n- 如属误操作可重新发起\n- 如有疑问请联系人工客服"
        )

    if not products:
        return (
            f"### 暂时没有找到相关商品\n\n"
            f"没有检索到与「**{keyword}**」匹配的在售商品，你可以：\n\n"
            "1. 换个关键词（如 狗粮 / 猫砂 / 玩具）再试\n"
            "2. 到首页浏览全部分类商品"
        )

    rows = "\n".join(
        f"| {p['id']} | {p['name']} | {p['category']} | "
        f"{p.get('suitable') or '通用'} | ¥{p['price']:.2f} | {p['stock']} |"
        for p in products
    )

    is_compare = (
        "、" in keyword or any(h in question for h in _COMPARE_HINTS)
    )
    title = (
        f"### ⚖️ 商品对比（{keyword}）\n\n"
        if is_compare
        else f"### 🛍️ 为你推荐的商品（{keyword}）\n\n"
    )
    lead = (
        f"实时读取商城数据库，为你整理了 **{len(products)}** 件商品，"
        "可从分类、适用对象、价格与库存几个维度对比：\n\n"
        if is_compare
        else f"实时读取商城数据库，共找到 **{len(products)}** 件在售商品：\n\n"
    )

    parts = [title, lead]
    note = state.get("recommend_note")
    if note:
        # 说明这次的推荐用到了照片识别结果（以及可信度在哪一档）
        parts.append(f"📷 {note}\n\n")
    parts.append(
        "| ID | 商品 | 分类 | 适用 | 价格 | 库存 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{rows}\n"
    )

    cheapest = min(products, key=lambda p: p["price"])
    if is_compare:
        parts.append(
            f"\n💡 **对比小结：** 预算优先可选 **{cheapest['name']}**"
            f"（¥{cheapest['price']:.2f}）；建议结合适用对象与库存决定。\n"
        )
    else:
        hot = [p for p in products if "热销" in (p.get("tags") or [])]
        if hot:
            parts.append(
                "\n🔥 **热销推荐：** "
                + "、".join(f"**{p['name']}**" for p in hot[:3])
                + "\n"
            )

    if _wants_code_sample(question):
        parts.append(_code_sample_appendix(products))

    parts.append(
        "\n\n> 告诉我商品编号和数量（如「买 #2 两件」），我可以帮你核算价格与配送。"
    )
    return "".join(parts)


def _write_order(state: WorkflowState) -> str:
    question = state["question"]
    decision = state.get("review_decision")
    lines = state.get("order_lines", [])
    total = float(state.get("total", 0.0) or 0.0)
    delivery = state.get("delivery_info", {}) or {}
    current_time = state.get("current_time", "")
    # 门店营业时间查询：命中时直接回答，不走订单核算逻辑
    store = state.get("store_info")
    if store:
        weekend = "（含周末）" if store.get("is_holiday") else ""
        return (
            f"### 🏪 {store['city']}门店信息\n\n"
            f"- **营业时间**：{store['hours']}{weekend}\n"
            f"- **联系电话**：{store['phone']}\n"
            f"- **门店地址**：{store['address']}\n"
            f"- **提示**：{store['note']}"
        )


    if decision == "rejected":
        return (
            "### 订单操作已驳回\n\n"
            f"你请求的操作「**{question}**」**已被取消**，我不会继续执行。\n\n"
            "- 如属误操作，可重新发起请求\n"
            "- 如有疑问，请联系人工客服处理"
        )

    if delivery.get("no_matched_product") or not lines:
        if decision == "approved":
            reasons = state.get("review_reasons", [])
            hit = "、".join(
                k for k in SENSITIVE_KEYWORDS if k in question
            ) or "敏感操作"
            return (
                "### ✅ 人工审核已通过\n\n"
                f"你请求的「**{hit}**」已通过人工审核。"
                "退款、取消订单等操作涉及账户与资金安全，聊天助手无法直接执行，"
                "请通过 **订单页** 自助操作，或联系 **人工客服** 为你处理。\n"
                + (f"\n> 审核记录：{'；'.join(reasons)}" if reasons else "")
            )
        return (
            "### 没能识别出你要下单的商品\n\n"
            "你可以这样告诉我：\n\n"
            "- **按商品名**：「买两袋狗粮」「我要 1 个逗猫棒」\n"
            "- **按商品编号**：「下单 #2 两件」（编号可在商品推荐表中查看）\n\n"
            f"🕐 当前时间：{current_time or '—'}"
        )

    rows = "\n".join(
        f"| {ln['name']} | {ln['unit_price']:.2f} | {ln['quantity']} | "
        f"{'✅' if ln['available'] else '❌ 库存不足'} | {ln['subtotal']:.2f} |"
        for ln in lines
    )
    unavailable = [ln for ln in lines if not ln["available"]]

    parts = ["### 🧾 订单核算结果"]
    if decision == "approved":
        parts.append("\n> ✅ **人工审核已通过**，订单明细确认如下：\n")
    parts.append(
        "\n| 商品 | 单价 | 数量 | 库存 | 小计 |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{rows}\n"
    )
    parts.append(
        f"\n- 商品合计：**¥{total:.2f}**"
        f"\n- 运费（{delivery.get('region', '默认地区')}）："
        f"**¥{delivery.get('shipping_fee', 0.0):.2f}**"
        f"\n- 预计时效：**{delivery.get('eta_days', '—')}**"
    )
    payable = total + float(delivery.get("shipping_fee", 0.0) or 0.0)
    parts.append(f"\n- **应付总额：¥{payable:.2f}**")
    if current_time:
        parts.append(f"\n- 🕐 核算时间：{current_time}")
    if unavailable:
        parts.append(
            "\n\n⚠️ 以下商品库存不足，请调整数量："
            + "、".join(f"**{ln['name']}**（剩 {ln.get('stock', 0)} 件）" for ln in unavailable)
        )
    parts.append(
        "\n\n> 这是聊天助手的订单核算结果，确认无误后请到 **购物车** 提交正式订单。"
    )
    return "".join(parts)


def writer_node(state: WorkflowState) -> dict:
    """根据意图与审核决定，组织最终 Markdown 回答。"""
    # 识别不可信、被人工驳回：与具体意图无关，统一告知"本次不采信照片信息"。
    # 放在最前面统一处理，免得三种回答各写一份。
    if (
        state.get("review_decision") == "rejected"
        and state.get("confidence_grade") == "low"
        and state.get("pet_profile")
    ):
        return {"answer": (
            "### 识别结果未通过人工确认\n\n"
            "这张照片没能得到足够可信的识别结果，人工审核未通过，"
            "所以**这次不采信照片里的信息**。\n\n"
            "- 可以重拍一张清晰、正面的猫/狗照片再试\n"
            "- 也可以直接说明需求，例如「推荐几款猫粮」\n"
        )}

    if state.get("intent") == INTENT_SHOPPING:
        answer = _write_shopping(state)
    elif state.get("intent") == INTENT_ORDER:
        answer = _write_order(state)
    else:
        answer = _write_knowledge(state)
    return {"answer": answer}
