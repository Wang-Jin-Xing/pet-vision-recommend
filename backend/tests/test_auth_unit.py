"""认证工具单元测试：bcrypt 哈希、JWT 签发/解析、过期与伪造令牌。"""
from datetime import timedelta

import pytest
from jose import jwt

from auth import create_access_token, hash_password, verify_password
from config import settings


def test_hash_password_不等于明文且可校验():
    raw = "s3cret-pwd"
    hashed = hash_password(raw)
    assert hashed != raw
    assert hashed.startswith("$2")  # bcrypt 哈希前缀
    assert verify_password(raw, hashed) is True


def test_verify_password_错误密码返回False():
    hashed = hash_password("correct-password")
    assert verify_password("wrong-password", hashed) is False


def test_两次哈希结果不同_加盐随机():
    assert hash_password("same-password") != hash_password("same-password")


def test_create_access_token_携带用户id():
    token = create_access_token(subject="42")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "42"
    assert "exp" in payload


def test_create_access_token_过期令牌解码失败():
    token = create_access_token(
        subject="1", expires_minutes=-1
    )  # 已于 1 分钟前过期
    with pytest.raises(Exception):  # jose 抛出 ExpiredSignatureError
        jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_伪造签名的令牌无法通过校验():
    forged = jwt.encode(
        {"sub": "1"}, "attacker-secret", algorithm=settings.ALGORITHM
    )
    with pytest.raises(Exception):  # jose 抛出 JWSSignatureError / JWTError
        jwt.decode(forged, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
