"""鉴权接口集成测试：注册、登录、JWT 保护、重复注册与错误密码。"""
import uuid


def _unique_email():
    return f"u{uuid.uuid4().hex[:10]}@test.com"


def test_健康检查(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_注册成功返回201且不含密码(client):
    email = _unique_email()
    resp = client.post(
        "/api/register",
        json={"email": email, "username": "新用户", "password": "123456"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == email
    assert "password" not in data
    assert "hashed_password" not in data


def test_注册非法邮箱返回422(client):
    resp = client.post(
        "/api/register",
        json={"email": "bad-email", "username": "u", "password": "123456"},
    )
    assert resp.status_code == 422


def test_重复邮箱注册返回400(client):
    email = _unique_email()
    body = {"email": email, "username": "甲", "password": "123456"}
    assert client.post("/api/register", json=body).status_code == 201
    resp = client.post(
        "/api/register",
        json={"email": email, "username": "乙", "password": "123456"},
    )
    assert resp.status_code == 400


def test_登录成功返回令牌(client, make_user):
    user, password = make_user(email=_unique_email())
    resp = client.post(
        "/api/login", json={"email": user.email, "password": password}
    )
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_登录错误密码返回401(client, make_user):
    user, _ = make_user(email=_unique_email())
    resp = client.post(
        "/api/login", json={"email": user.email, "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_登录不存在的邮箱返回401(client):
    resp = client.post(
        "/api/login",
        json={"email": "nobody@test.com", "password": "whatever1"},
    )
    assert resp.status_code == 401


def test_me_无令牌返回401(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_me_伪造令牌返回401(client):
    resp = client.get(
        "/api/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert resp.status_code == 401


def test_me_合法令牌返回当前用户(client, auth_headers):
    resp = client.get("/api/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "login@test.com"
