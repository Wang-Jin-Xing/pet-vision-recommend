"""pytest 公共夹具。

关键约束：config.settings / database.engine 在模块导入时即按环境变量定型，
因此必须在导入任何应用模块「之前」把 DATABASE_URL 等指向临时测试目录。
pytest 会最先加载本 conftest，可保证这一顺序。
"""
import os
import sys
import tempfile
from pathlib import Path

# ---- 1. 在导入应用前准备隔离的测试环境变量 ----
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="petpals-pytest-"))

# 让 `import models / import main` 等扁平导入可用
sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TEST_ROOT / "uploads")
os.environ["CHROMA_DIR"] = str(_TEST_ROOT / "chroma")
os.environ["PET_IMAGE_DIR"] = str(_TEST_ROOT / "pet_images")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import models  # noqa: E402
import database  # noqa: E402
from auth import hash_password  # noqa: E402
from main import app  # noqa: E402
from database import get_db  # noqa: E402


@pytest.fixture()
def db():
    """每个测试用例一个全新的内存 SQLite，结束即销毁，用例间完全隔离。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 单连接复用，保证内存库在用例期间不消失
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db):
    """覆盖 get_db 依赖，使 HTTP 请求走用例的内存库。"""

    def _override_get_db():
        try:
            yield db
        finally:
            # 不在此关闭：db 由 db fixture 统一管理生命周期
            pass

    app.dependency_overrides[get_db] = _override_get_db
    # 清空登录/注册内存限流器，避免用例间（同 IP）相互触发 429
    from routers import auth as auth_router

    auth_router._rate_hits.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db):
    """工厂夹具：直接在库中创建用户，返回 (user, 明文密码)。"""

    def _make(email="user@test.com", username="测试用户", password="test123456",
              is_admin=False):
        user = models.User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user, password

    return _make


@pytest.fixture()
def auth_headers(client, make_user):
    """注册并登录一个普通用户，返回带 Authorization 的请求头。"""
    user, password = make_user(email="login@test.com", username="登录用户")
    resp = client.post(
        "/api/login", json={"email": user.email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def make_product(db):
    """工厂夹具：创建商品。"""

    def _make(name="测试狗粮", price=89.0, stock=100, category="宠物食品"):
        product = models.Product(
            name=name, price=price, stock=stock, category=category, tags=[]
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        return product

    return _make


@pytest.fixture()
def offline_llm(monkeypatch):
    """让所有 LLM 调用回落本地确定性逻辑——测试不联网。

    项目根 .env 里可能配了真实 LLM_API_KEY，conftest 不会清掉它，
    凡是要跑工作流的用例都应该带上这个夹具做隔离。
    """
    from agents import llm as llm_helper

    monkeypatch.setattr(llm_helper, "get_llm", lambda: None)
