# -*- coding: utf-8 -*-
"""聊天接口接宠物档案的测试：选用已有档案 → 推荐按档案条件走。"""


def _login(client, make_user, email):
    _, pw = make_user(email=email, username=email.split("@")[0])
    r = client.post("/api/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_pet(client, headers, **over):
    body = {"name": "小黑", "species": "猫", "size": "中型",
            "coat_condition": "毛发枯燥", "confidence": 0.9}
    body.update(over)
    r = client.post("/api/pets", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class Test用档案聊天:
    def test_带上档案会后按档案筛选(self, client, auth_headers, offline_llm):
        pid = _create_pet(client, auth_headers)
        r = client.post(
            "/api/chat",
            json={"message": "推荐几款猫粮", "pet_profile_id": pid},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert "📷" in r.json()["answer"]

    def test_不带档案时行为不变(self, client, auth_headers, offline_llm):
        r = client.post(
            "/api/chat", json={"message": "推荐几款商品"}, headers=auth_headers
        )
        assert r.status_code == 200
        assert "📷" not in r.json()["answer"]

    def test_档案不存在返回404(self, client, auth_headers, offline_llm):
        r = client.post(
            "/api/chat",
            json={"message": "推荐商品", "pet_profile_id": 99999},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_不能使用别人的档案(self, client, make_user, offline_llm):
        a = _login(client, make_user, "a@test.com")
        pid = _create_pet(client, a)

        b = _login(client, make_user, "b@test.com")
        r = client.post(
            "/api/chat",
            json={"message": "推荐商品", "pet_profile_id": pid},
            headers=b,
        )
        assert r.status_code == 404

    def test_低置信档案聊天会触发人工审核(self, client, auth_headers, offline_llm):
        pid = _create_pet(client, auth_headers, confidence=0.2)
        r = client.post(
            "/api/chat",
            json={"message": "推荐几款猫粮", "pet_profile_id": pid},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["review_required"] is True
        assert any("识别" in x for x in body["review"]["reasons"])

    def test_流式接口也支持档案(self, client, auth_headers, offline_llm):
        pid = _create_pet(client, auth_headers)
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "推荐几款猫粮", "pet_profile_id": pid},
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            text = "".join(resp.iter_text())
        assert "📷" in text
