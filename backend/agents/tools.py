"""Agent 工具集。

两部分：
1. ChromaDB 向量库的写入 / 检索（ingest_text / retrieve）——供文档上传与
   知识检索使用；
2. 5 个 LangChain @tool 工具（供多 Agent 工作流中的专职 Agent 调用）：
   - search_pet_care   ：养宠知识向量检索
   - recommend_products：商品推荐（实时读数据库，不硬编码）
   - calculate_total   ：订单价格核算（单价实时读数据库）
   - check_delivery    ：库存与配送评估（库存实时读数据库）
   - get_current_time  ：当前时间

结构化结果以 JSON 字符串返回，节点侧 json.loads 后写入 WorkflowState。
"""
import json
import logging
import math
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import chromadb
from langchain_core.tools import tool
from sqlalchemy import or_

from config import settings
from database import SessionLocal
from models import Product

logger = logging.getLogger("petpals")

# ======================================================================
# ChromaDB 向量库
# ======================================================================

_client = None


def get_collection():
    """懒加载 ChromaDB 持久化客户端与集合。"""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
    return _client.get_or_create_collection(name=settings.COLLECTION_NAME)


CHUNK_SIZE = 500


def _split_sections(text: str) -> List[str]:
    """按 Markdown 标题与空行拆成小节；超长小节再按段落/定长细分。

    相比 500 字硬切，尽量保证「剪指甲」「犬细小」这类小节完整，
    避免关键信息被切到两个片段。
    """
    raw_sections: List[List[str]] = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip().startswith("#") and current:
            raw_sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        raw_sections.append(current)

    parts: List[str] = []
    for lines in raw_sections:
        sec = "\n".join(lines).strip()
        if not sec:
            continue
        if len(sec) <= CHUNK_SIZE:
            parts.append(sec)
            continue
        buf = ""
        for para in re.split(r"\n\s*\n", sec):
            para = para.strip()
            if not para:
                continue
            if len(para) > CHUNK_SIZE:
                if buf:
                    parts.append(buf)
                    buf = ""
                parts += [
                    para[i:i + CHUNK_SIZE]
                    for i in range(0, len(para), CHUNK_SIZE)
                ]
            elif buf and len(buf) + len(para) + 1 > CHUNK_SIZE:
                parts.append(buf)
                buf = para
            else:
                buf = f"{buf}\n{para}" if buf else para
        if buf:
            parts.append(buf)
    return parts


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    """章节感知切块：贪心把相邻小节打包进不超过 500 字的片段。"""
    sections = _split_sections(text)
    packed: List[str] = []
    buf = ""
    for sec in sections:
        if buf and len(buf) + len(sec) + 2 > chunk_size:
            packed.append(buf)
            buf = sec
        else:
            buf = f"{buf}\n\n{sec}" if buf else sec
    if buf:
        packed.append(buf)
    return packed


def ingest_text(doc_id: int, text: str, filename: str) -> int:
    """把文档切块写入 ChromaDB。向量库不可用时静默降级，返回写入块数。"""
    chunks = _chunk_text(text)
    if not chunks:
        return 0
    try:
        collection = get_collection()
        collection.add(
            ids=[f"doc-{doc_id}-chunk-{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"doc_id": doc_id, "filename": filename} for _ in chunks],
        )
        return len(chunks)
    except Exception:  # 例如首次使用需下载嵌入模型且网络不可用
        logger.exception("写入向量库失败，已跳过 doc_id=%s", doc_id)
        return 0


def _lexical_terms(text: str) -> Tuple[set, set]:
    """抽取中文词法特征：二元字组（权重高）+ 单个汉字 + 英文词。

    默认嵌入模型 all-MiniLM-L6-v2 对中文语义区分弱，
    用词法命中（驱虫/疫苗/洗澡等领域词均为二元字组）兜底。
    """
    cjk = "".join(re.findall(r"[一-鿿]", text))
    bigrams = {cjk[i:i + 2] for i in range(len(cjk) - 1)}
    words = {w.lower() for w in re.findall(r"[a-zA-Z]{2,}", text)}
    return bigrams, (set(cjk) | words)


# 中文疑问/客套类高频二元组，检索意图判别价值低，命中不应加分
_LEXICAL_STOP_BIGRAMS = {
    "多久", "一次", "几次", "怎么", "怎样", "如何", "什么", "为啥", "为何",
    "为什", "可以", "多少", "哪些", "请问", "应该", "我们", "他们", "它们",
    "这个", "那个", "还是", "比较", "一下", "时候", "现在",
}

# 单字只作弱信号（0.4 权重），避免常见字堆叠压过领域二元组
_UNIGRAM_WEIGHT = 0.4


def retrieve(query: str, top_k: int = 3) -> List[str]:
    """混合检索 TopK 资料片段：中文词法（IDF 加权，0.75）+ 向量相似度（0.25）。

    词法排序修正嵌入模型对中文区分弱的问题，向量补充近义表述召回；
    任何异常都降级为纯词法（全部片段仍在本地集合中）。
    """
    try:
        collection = get_collection()
        total = collection.count()
        if total == 0:
            return []

        all_data = collection.get(include=["documents", "metadatas"])
        all_items = [
            (cid, doc, (meta or {}).get("filename", ""))
            for cid, doc, meta in zip(
                all_data.get("ids") or [],
                all_data.get("documents") or [],
                all_data.get("metadatas") or [],
            )
            if doc
        ]
        if not all_items:
            return []

        # ---- 词法排序（对全量片段打分，IDF 加权）----
        # 先统计每个特征在多少个片段中出现：罕见领域词（驱虫/疫苗/指甲）
        # 权重高，"多久/一次"等通用词权重低
        n_docs = len(all_items)
        doc_freq: Dict[str, int] = {}
        term_sets: List[Tuple[set, set]] = []
        for _cid, doc, filename in all_items:
            d_bi, d_one = _lexical_terms(doc)
            f_bi, f_one = _lexical_terms(filename)
            # 文件名作为高信号上下文并入该片段特征
            bi, one = d_bi | f_bi, d_one | f_one
            term_sets.append((bi, one))
            for term in bi | one:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        def _weight(term: str) -> float:
            return math.log(1.0 + n_docs / (1 + doc_freq.get(term, 0)))

        q_bi_raw, q_one = _lexical_terms(query)
        q_bi = q_bi_raw - _LEXICAL_STOP_BIGRAMS
        lex_scores: Dict[str, float] = {}
        for idx, (cid, _doc, _fn) in enumerate(all_items):
            d_bi, d_one = term_sets[idx]
            score = 2.0 * sum(_weight(t) for t in (q_bi & d_bi)) + _UNIGRAM_WEIGHT * sum(
                _weight(t) for t in (q_one & d_one)
            )
            if score > 0:
                lex_scores[cid] = score
        max_lex = max(lex_scores.values(), default=1.0) or 1.0

        # ---- 向量打分（距离转相似度）----
        vec_sims: Dict[str, float] = {}
        try:
            result = collection.query(
                query_texts=[query],
                n_results=min(top_k * 3, n_docs),
                include=["distances"],
            )
            vec_ids = (result.get("ids") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            sims = [1.0 / (1.0 + d) for d in distances]
            max_sim = max(sims, default=1.0) or 1.0
            vec_sims = {cid: s / max_sim for cid, s in zip(vec_ids, sims)}
        except Exception:
            logger.warning("向量检索失败，仅用词法排序", exc_info=True)

        # ---- 归一化加权融合：词法主导，向量只做近义召回的补充 ----
        fused = [
            (
                0.75 * (lex_scores.get(cid, 0.0) / max_lex)
                + 0.25 * vec_sims.get(cid, 0.0),
                doc,
            )
            for cid, doc, _fn in all_items
        ]
        fused.sort(key=lambda x: -x[0])

        seen, unique = set(), []
        for _, doc in fused:
            if doc not in seen:
                seen.add(doc)
                unique.append(doc)
            if len(unique) >= top_k:
                break
        return unique
    except Exception:
        logger.warning("混合检索失败，已降级为空结果", exc_info=True)
        return []


# =====================================================================
# 内部数据库查询辅助（被 @tool 包装函数复用）
# =====================================================================

def _product_to_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "price": round(p.price, 2),
        "category": p.category,
        "suitable": p.suitable,
        # 结构化适用条件：供「按宠物档案筛选」使用（suitable 只是展示文案）
        "species": p.species,
        "size": p.size,
        "stage": p.stage,
        "stock": p.stock,
        "tags": p.tags or [],
    }


def query_products(
    keyword: str = "",
    category: str = "",
    only_in_stock: bool = True,
    limit: int = 5,
) -> List[dict]:
    """从数据库实时查询商品：关键词模糊匹配名称/描述，可叠加分类筛选。"""
    session = SessionLocal()
    try:
        query = session.query(Product)
        if only_in_stock:
            query = query.filter(Product.stock > 0)
        if category:
            query = query.filter(Product.category == category)
        keyword = (keyword or "").strip()
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                or_(Product.name.like(like), Product.description.like(like))
            )
        rows = query.order_by(Product.id).limit(limit).all()
        return [_product_to_dict(p) for p in rows]
    finally:
        session.close()


def list_categories() -> List[str]:
    """读取数据库中实际存在的商品分类。"""
    session = SessionLocal()
    try:
        rows = session.query(Product.category).distinct().all()
        return [r[0] for r in rows if r[0]]
    finally:
        session.close()


# =====================================================================
# 5 个 LangChain @tool 工具
# =====================================================================

@tool
def search_pet_care(query: str, top_k: int = 3) -> str:
    """检索宠物饲养知识库。当用户询问喂养、疫苗、驱虫、洗澡、行为训练等
    养宠知识时使用。返回 JSON：{"found": 是否命中, "chunks": 资料片段列表}。"""
    chunks = retrieve(query, top_k=top_k)
    return json.dumps({"found": bool(chunks), "chunks": chunks}, ensure_ascii=False)


@tool
def recommend_products(
    keyword: str = "",
    category: str = "",
    limit: int = 5,
) -> str:
    """从商城数据库实时推荐在售商品。keyword 在商品名称/描述中模糊匹配，
    category 按分类精确筛选（如 宠物食品/玩具/洗护/零食/日用品），
    limit 控制返回数量。返回 JSON：{"count": 数量, "products": [...]}，
    商品价格与库存均为数据库实时数据。"""
    limit = max(1, min(int(limit or 5), 20))
    products = query_products(keyword=keyword, category=category, limit=limit)
    return json.dumps(
        {"keyword": keyword, "category": category, "count": len(products), "products": products},
        ensure_ascii=False,
    )


@tool
def calculate_total(items: list) -> str:
    """按商品列表核算订单金额，单价实时读取数据库。
    items 形如 [{"product_id": 1, "quantity": 2}, ...]。
    返回 JSON：每行小计、是否全部可售、缺失/下架商品以及合计 total。"""
    lines = []
    missing = []
    total = 0.0

    session = SessionLocal()
    try:
        for raw in items or []:
            pid = raw.get("product_id")
            qty = int(raw.get("quantity", 1) or 1)
            if qty <= 0:
                qty = 1
            product = session.get(Product, pid) if isinstance(pid, int) else None
            if product is None:
                missing.append({"product_id": pid, "reason": "商品不存在"})
                lines.append(
                    {
                        "product_id": pid,
                        "name": f"商品 {pid}",
                        "quantity": qty,
                        "unit_price": 0.0,
                        "subtotal": 0.0,
                        "available": False,
                    }
                )
                continue

            available = product.stock >= qty and product.stock > 0
            subtotal = round(product.price * qty, 2)
            if available:
                total += subtotal
            lines.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "quantity": qty,
                    "unit_price": round(product.price, 2),
                    "subtotal": subtotal,
                    "available": available,
                    "stock": product.stock,
                }
            )
            if not available:
                missing.append(
                    {"product_id": pid, "reason": f"库存不足（剩余 {product.stock}）"}
                )
    finally:
        session.close()

    return json.dumps(
        {
            "lines": lines,
            "missing": missing,
            "all_available": len(missing) == 0,
            "total": round(total, 2),
        },
        ensure_ascii=False,
    )


# 地区 -> (运费, 预计天数) 的业务规则（非商品数据，属于配送策略）
_DELIVERY_RULES = [
    (("北京", "上海", "广州", "深圳", "同城"), 0.0, (1, 2)),
    (("江苏", "浙江", "广东", "华东", "华南"), 8.0, (2, 3)),
    (("新疆", "西藏", "青海", "内蒙"), 18.0, (5, 7)),
]
DEFAULT_DELIVERY = (10.0, (3, 5))


@tool
def check_delivery(region: str = "", items: Optional[list] = None) -> str:
    """评估配送可行性与预计时效。region 为收货地区（省/市关键词即可）；
    items 可选，形如 [{"product_id":1,"quantity":2}]，传入时会实时核对库存。
    返回 JSON：{"can_deliver","stock_ok","region","shipping_fee","eta_days"}。"""
    region = (region or "").strip()

    fee, eta = DEFAULT_DELIVERY
    for keywords, rule_fee, rule_eta in _DELIVERY_RULES:
        if any(k in region for k in keywords):
            fee, eta = rule_fee, rule_eta
            break

    stock_ok = True
    stock_detail = []
    if items:
        session = SessionLocal()
        try:
            for raw in items:
                pid = raw.get("product_id")
                qty = int(raw.get("quantity", 1) or 1)
                product = session.get(Product, pid) if isinstance(pid, int) else None
                enough = bool(product and product.stock >= qty)
                stock_ok = stock_ok and enough
                stock_detail.append(
                    {
                        "product_id": pid,
                        "need": qty,
                        "stock": product.stock if product else 0,
                        "enough": enough,
                    }
                )
        finally:
            session.close()

    return json.dumps(
        {
            "region": region or "默认地区",
            "can_deliver": True,
            "stock_ok": stock_ok,
            "stock_detail": stock_detail,
            "shipping_fee": fee,
            "eta_days": f"{eta[0]}-{eta[1]} 个工作日",
        },
        ensure_ascii=False,
    )


@tool
def get_current_time() -> str:
    """获取当前日期与时间（下单、时效咨询时使用）。
    返回 JSON：{"datetime": "YYYY-MM-DD HH:MM:SS", "weekday": 星期几}。"""
    now = datetime.now()
    weekdays = "一二三四五六日"
    return json.dumps(
        {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": f"星期{weekdays[now.weekday()]}",
        },
        ensure_ascii=False,
    )
# 门店营业时间表（模拟数据，真实项目应查数据库/接口）
_STORE_HOURS = {
    "北京": {"hours": "09:00-21:00", "phone": "010-8888-0001", "address": "朝阳区建国路 88 号"},
    "上海": {"hours": "09:30-21:30", "phone": "021-6666-0002", "address": "浦东新区世纪大道 100 号"},
    "广州": {"hours": "10:00-22:00", "phone": "020-3333-0003", "address": "天河区天河路 200 号"},
    "深圳": {"hours": "10:00-22:00", "phone": "0755-2222-0004", "address": "南山区深南大道 300 号"},
    "沧州": {"hours": "08:30-20:00", "phone": "0317-1111-0005", "address": "运河区新华路 66 号"},
}
_STORE_DEFAULT = {"hours": "09:00-21:00", "phone": "400-000-8888", "address": "线上商城（全国配送）"}


@tool
def get_store_hours(city: str = "", date: str = "") -> str:
    """查询宠物门店的营业时间、联系电话与地址。当用户询问门店几点开门、
    几点关门、周末/节假日是否营业、门店在哪、门店电话时使用。
    city 为城市名（如 北京/上海/广州/深圳/沧州），date 可选（如 周末/节假日）。
    返回 JSON：{"city": 城市, "hours": 营业时间, "phone": 电话,
    "address": 地址, "is_holiday": 是否节假日, "note": 补充说明}。"""
    city = (city or "").strip()
    date = (date or "").strip()

    # 城市匹配：先精确、再包含（如"北京市"也能命中"北京"）
    info = _STORE_HOURS.get(city)
    if info is None:
        for name, v in _STORE_HOURS.items():
            if name in city or city in name:
                city, info = name, v
                break
    matched = info is not None
    info = info or _STORE_DEFAULT
    if not city:
        city = "线上"

    # 节假日 / 周末提示
    is_holiday = any(k in date for k in ("周末", "节假", "节", "国庆", "春节", "元旦"))
    now = datetime.now()
    today_is_weekend = now.weekday() >= 5
    is_holiday = is_holiday or today_is_weekend

    note = "节假日正常营业，高峰时段可能排队，建议提前致电确认。"
    if not matched and city not in ("线上", ""):
        note = f"暂未收录「{city}」的实体门店，以下为线上商城服务时间。"
        info = _STORE_DEFAULT

    return json.dumps(
        {
            "city": city,
            "hours": info["hours"],
            "phone": info["phone"],
            "address": info["address"],
            "is_holiday": is_holiday,
            "matched_store": matched,
            "note": note,
        },
        ensure_ascii=False,
    )


# 工具清单（供后续接入大模型 bind_tools / AgentExecutor 使用）
ALL_TOOLS = [
    search_pet_care,
    recommend_products,
    get_store_hours,
    calculate_total,
    check_delivery,
    get_current_time,
]
