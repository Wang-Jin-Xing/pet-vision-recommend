"""SQLAlchemy 2.0：引擎、Session 工厂、声明式基类与 get_db 依赖注入。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

# SQLite 引擎；check_same_thread=False 允许 FastAPI 多线程请求共用连接
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Session 工厂
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类（SQLAlchemy 2.0 风格）。"""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求获取独立 Session，请求结束自动关闭。"""
    with SessionLocal() as db:
        yield db
