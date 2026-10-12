"""FastAPI 应用入口：中间件、路由注册、建表与演示数据。"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import models
from config import settings
from database import SessionLocal, engine
from routers import auth, chat, history, orders, pets, products, upload
from routers.chat import review_router

logger = logging.getLogger("petpals")


def _migrate_sqlite() -> None:
    """SQLite 开发库的轻量幂等迁移（学习版替代 Alembic）。

    `create_all` 只会**新建表**，不会给已存在的表补列；新增字段必须在这里手动 ALTER。
    每段都先查列是否存在再动手，重复启动无副作用。
    注意：本函数在 `create_all` **之前**执行，全新库此时还没有表，PRAGMA 返回空即跳过。
    """
    with engine.begin() as conn:
        _migrate_conversations_thread_id(conn)
        _migrate_products_attrs(conn)


def _migrate_conversations_thread_id(conn) -> None:
    """旧库的 conversations 缺少 thread_id 时补上，并按主键回填唯一值。"""
    cols = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
    if not cols:
        return  # 全新库，create_all 会直接建出带 thread_id 的表
    if any(row[1] == "thread_id" for row in cols):
        return
    conn.execute(
        text("ALTER TABLE conversations ADD COLUMN thread_id VARCHAR(64)")
    )
    conn.execute(
        text("UPDATE conversations SET thread_id = 'conv-' || id "
             "WHERE thread_id IS NULL")
    )
    conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ix_conversations_thread_id "
             "ON conversations (thread_id)")
    )


def _migrate_products_attrs(conn) -> None:
    """给 products 补三个结构化列：species / size / stage（见 models.Product 注释）。"""
    cols = conn.execute(text("PRAGMA table_info(products)")).fetchall()
    if not cols:
        return
    existing = {row[1] for row in cols}
    for name in ("species", "size", "stage"):
        if name not in existing:
            conn.execute(text(f"ALTER TABLE products ADD COLUMN {name} VARCHAR(16)"))


_migrate_sqlite()

# 启动时自动建表（SQLite 开发阶段使用，生产环境建议换 Alembic 迁移）
models.Base.metadata.create_all(bind=engine)


# suitable 展示文案 → 结构化属性（species, size, stage）。
# 只用于**旧库回填**；新增商品请直接写三列，别再依赖中文文案。
_SUITABLE_MAP = {
    "成犬": ("dog", "all", "adult"),
    "成猫": ("cat", "all", "adult"),
    "幼犬": ("dog", "all", "puppy"),
    "幼猫": ("cat", "all", "puppy"),
    "全阶段": ("both", "all", "all"),
    "全阶段猫咪": ("cat", "all", "all"),
    "犬猫通用": ("both", "all", "all"),
    "中小型犬": ("dog", "medium", "all"),
}


def _backfill_product_attrs(db) -> int:
    """给「已有但结构化列为空」的商品回填 species/size/stage，返回回填条数。

    幂等：只处理三列为空的记录，重复启动不会覆盖人工调整过的值。
    """
    rows = db.query(models.Product).filter(models.Product.species.is_(None)).all()
    if not rows:
        return 0
    for p in rows:
        species, size, stage = _SUITABLE_MAP.get(
            (p.suitable or "").strip(), ("both", "all", "all")  # 认不出就按最宽松处理
        )
        p.species, p.size, p.stage = species, size, stage
    db.commit()
    return len(rows)


def seed_products() -> None:
    """商品表为空时插入演示数据，方便首页直接看到效果。"""
    db = SessionLocal()
    try:
        _backfill_product_attrs(db)  # 旧库：给已有商品补上结构化列
        if db.query(models.Product).count() > 0:
            return
        demo_products = [
            models.Product(name="成犬全价狗粮 1.5kg", category="宠物食品",
                           description="营养均衡，适合 1-7 岁成犬日常食用。",
                           suitable="成犬", species="dog", size="all", stage="adult",
                           tags=["热销", "全犬种"],
                           price=89.0, stock=100),
            models.Product(name="深海鱼味营养猫粮 2kg", category="宠物食品",
                           description="富含牛磺酸与 Omega-3，猫咪爱吃。",
                           suitable="成猫", species="cat", size="all", stage="adult",
                           tags=["热销", "美毛"],
                           price=99.0, stock=100),
            models.Product(name="羽毛逗猫棒", category="玩具",
                           description="铃铛羽毛组合，增进人宠互动。",
                           suitable="全阶段猫咪", species="cat", size="all", stage="all",
                           tags=["互动"],
                           price=19.9, stock=200),
            models.Product(name="宠物温和沐浴露 500ml", category="洗护",
                           description="低敏配方，犬猫通用，留香持久。",
                           suitable="犬猫通用", species="both", size="all", stage="all",
                           tags=["低敏"],
                           price=39.9, stock=80),
            models.Product(name="洁齿磨牙骨 10 支装", category="零食",
                           description="清洁牙垢、清新口气，适合中小型犬。",
                           suitable="中小型犬", species="dog", size="medium", stage="all",
                           tags=["洁齿"],
                           price=25.0, stock=150),
            models.Product(name="结团除臭猫砂 10L", category="日用品",
                           description="快速结团，低尘除臭，用量更省。",
                           suitable="全阶段猫咪", species="cat", size="all", stage="all",
                           tags=["除臭", "低尘"],
                           price=49.0, stock=60),
        ]
        db.add_all(demo_products)
        db.commit()
    finally:
        db.close()


seed_products()


def seed_knowledge_base() -> None:
    """启动时把预置养宠文档索引进 ChromaDB 知识库（幂等）。

    扫描 UPLOAD_DIR 与 KNOWLEDGE_SEED_DIR（如配置）下的 txt/md 文件，
    对尚未索引的文件切块写入向量库。种子文档使用高位 doc_id（100000+）
    避免与用户上传文档冲突；不写入 Document 表（该表仅记录用户上传）。
    """
    import os

    from agents.tools import get_collection, ingest_text

    seed_dirs = [settings.UPLOAD_DIR]
    if (
        settings.KNOWLEDGE_SEED_DIR
        and os.path.abspath(settings.KNOWLEDGE_SEED_DIR)
        != os.path.abspath(settings.UPLOAD_DIR)
    ):
        seed_dirs.append(settings.KNOWLEDGE_SEED_DIR)

    files = []
    for d in seed_dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.lower().endswith((".txt", ".md")):
                files.append((name, os.path.join(d, name)))

    if not files:
        return

    try:
        collection = get_collection()
    except Exception:
        logger.exception("获取向量库集合失败，跳过知识种子索引")
        return

    indexed = 0
    for i, (name, path) in enumerate(sorted(files)):
        doc_id = 100000 + i
        # 幂等：首个 chunk 已存在则跳过该文档
        try:
            existing = collection.get(ids=[f"doc-{doc_id}-chunk-0"], limit=1)
            if existing.get("ids"):
                continue
        except Exception:
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            if ingest_text(doc_id, text, name) > 0:
                indexed += 1
        except Exception:
            logger.exception("索引种子文档失败：%s", name)

    logger.info("知识库种子索引完成，本次新增 %d 篇文档", indexed)


seed_knowledge_base()


app = FastAPI(title="PetPals 宠物生活服务平台 API", version="0.1.0")

# 跨域来源白名单（由 CORS_ORIGINS 配置，默认仅本地开发前端）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["health"])
def health_check():
    return {"status": "ok", "app": "PetPals"}


# 路由注册
app.include_router(auth.router, prefix="/api", tags=["鉴权"])
app.include_router(products.router, prefix="/api/products", tags=["商品"])
app.include_router(orders.router, prefix="/api/orders", tags=["订单"])
app.include_router(chat.router, prefix="/api/chat", tags=["AI 聊天"])
app.include_router(review_router, prefix="/api", tags=["人工审核"])
app.include_router(history.router, prefix="/api/history", tags=["历史对话"])
app.include_router(upload.router, prefix="/api", tags=["文档上传"])
app.include_router(pets.router, prefix="/api", tags=["宠物档案"])
