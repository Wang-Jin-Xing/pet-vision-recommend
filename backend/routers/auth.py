"""鉴权路由：POST /api/register 注册、POST /api/login 登录、GET /api/me 当前用户。"""
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import models
import schemas
from auth import create_access_token, get_current_user, hash_password, verify_password
from database import get_db

router = APIRouter()

# ======================================================================
# 轻量内存固定窗口限流（按客户端 IP），缓解登录爆破 / 注册刷库
# 单进程学习版足够；多进程部署需换成 Redis 等共享存储
# ======================================================================
_rate_lock = threading.Lock()
_rate_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(prefix: str, max_calls: int, window_seconds: float):
    """生成限流依赖：同一 IP 在 window_seconds 内最多调用 max_calls 次。"""

    def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{prefix}:{ip}"
        now = time.monotonic()
        with _rate_lock:
            hits = _rate_hits[key]
            deadline = now - window_seconds
            while hits and hits[0] <= deadline:
                hits.popleft()
            if len(hits) >= max_calls:
                raise HTTPException(
                    status_code=429,
                    detail="请求过于频繁，请稍后再试",
                    headers={"Retry-After": str(int(window_seconds))},
                )
            hits.append(now)
            # 防止空 deque 长期堆积
            if len(_rate_hits) > 5000:
                for k in [k for k, v in _rate_hits.items() if not v]:
                    del _rate_hits[k]

    return dependency


@router.post(
    "/register",
    response_model=schemas.UserOut,
    status_code=201,
    dependencies=[Depends(_rate_limit("register", max_calls=5, window_seconds=60))],
)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """用户注册：邮箱唯一，密码经 bcrypt 哈希后入库。"""
    exists = db.query(models.User).filter(models.User.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=schemas.Token,
    dependencies=[Depends(_rate_limit("login", max_calls=10, window_seconds=60))],
)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    """登录：校验邮箱与密码，成功返回 JWT（有效期 7 天）。"""
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    access_token = create_access_token(subject=str(user.id))
    return schemas.Token(access_token=access_token)


@router.get("/me", response_model=schemas.UserOut)
def read_me(current_user: models.User = Depends(get_current_user)):
    """携带 JWT 获取当前登录用户信息，用于验证登录态。"""
    return current_user
