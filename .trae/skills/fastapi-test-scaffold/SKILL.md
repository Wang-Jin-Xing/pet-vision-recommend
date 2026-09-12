---
name: "fastapi-test-scaffold"
description: "Scaffold layered pytest suites for FastAPI + SQLAlchemy apps (unit/schema/API): pre-import env isolation, in-memory SQLite, get_db override, auth & factory fixtures. Invoke when adding tests or a tests/ dir to a FastAPI backend."
---

# FastAPI + SQLAlchemy 分层测试脚手架

为 FastAPI + SQLAlchemy（2.0 声明式）后端快速建立可重复、零外部依赖的 pytest 测试体系。当需要"给后端补测试 / 新建 tests 目录 / 为新接口加测试"时使用。

## 分层约定

1. **纯单元测试**：不碰数据库与 HTTP（密码哈希、JWT、工具函数）。
2. **契约测试**：直接构造 Pydantic 模型，断言合法/非法输入（参数化覆盖非法值）。
3. **API 集成测试**：用 `TestClient` + 依赖覆盖走完整 HTTP 链路，断言状态码、响应体与数据库副作用（如库存扣减、回滚）。

文件建议：`tests/test_*_unit.py`、`tests/test_schemas.py`、`tests/test_api_*.py`。

## 关键陷阱与对策（必须遵守）

1. **环境变量必须在导入应用代码之前设置**：`config.settings` 与 `database.engine` 常在模块导入时定型。在 `conftest.py` 最顶部、所有应用 import 之前设置 `DATABASE_URL` 等（pytest 保证 conftest 最先加载）。
2. **用例级隔离用内存 SQLite + StaticPool**：`sqlite://` 默认每连接一个独立内存库，必须 `poolclass=StaticPool` 复用单连接，库在用例期间才不会消失。
3. **HTTP 与 ORM 必须看到同一个 session**：在 `client` fixture 中用 `app.dependency_overrides[get_db]` 覆盖为用例 session，这样测试代码 `db.refresh()` 才能断言接口产生的数据变化。
4. **每用例重建表**：在 db fixture 中 `Base.metadata.create_all`，结束 `session.close()` + `engine.dispose()`，用例间完全隔离，不依赖清理顺序。
5. **内存限流器/全局缓存要在用例间清空**，否则同 IP 的登录/注册用例会互相触发 429。
6. 扁平导入风格（`import models`）的项目：在 conftest 把后端目录 `sys.path.insert(0, ...)`，避免以脚本方式导入相对导入失败。
7. TestClient 依赖 **httpx**；把 `pytest`、`httpx` 放进 `requirements-dev.txt`，CI 中 `pip install -r requirements.txt -r requirements-dev.txt`。

## conftest.py 模板

```python
import os, sys, tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_ROOT = Path(tempfile.mkdtemp(prefix="app-pytest-"))
sys.path.insert(0, str(BACKEND_DIR))

# 必须在 import 应用模块之前
os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from main import app
from database import get_db


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    # 若路由有内存限流器/全局缓存，在此清空
    yield TestClient(app)
    app.dependency_overrides.clear()
```

再按需提供工厂夹具：`make_user`（直接入库并返回明文密码）、`auth_headers`（登录取 JWT 拼 Bearer 头）、`make_product` 等，减少重复构造代码。

## 必测场景清单（安全敏感项目尤其重要）

- 认证：无 token → 401、伪造/过期 token → 401、合法 token 正常；错误密码/未知账号 → 401；响应体不得含密码字段。
- 入参契约：非法邮箱、密码长度上下限、空集合、数量边界、枚举白名单 → 422。
- 业务规则与副作用：成功后断言 DB 状态变化；失败路径断言**回滚**（如库存不足时库存不变）；唯一约束冲突 → 4xx。
- 越权：A 用户不能读/改 B 用户资源 → 403；资源不存在 → 404。
- 健康检查与公开接口基线 200。

## 运行与验收

```bash
pytest -q                       # 全部通过，无残留测试库文件
pytest tests/ --co -q           # 检查收集列表
```

测试不得写入真实数据库或持久目录；全部副作用落在内存库或系统临时目录。
