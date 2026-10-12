# -*- coding: utf-8 -*-
"""宠物档案接口测试：识别（不入库）→ 建档 → 列表 → 删除，以及按用户隔离。

视觉模型一律用 stub 替掉，测试不联网、不依赖 API Key。
"""
import io

import pytest

from agents import vision

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128


def _post_image(client, headers):
    return client.post(
        "/api/vision/classify",
        files={"file": ("pet.jpg", io.BytesIO(JPEG), "image/jpeg")},
        headers=headers,
    )


@pytest.fixture()
def stub_vision(monkeypatch):
    """把识别结果换成可控值。用法：stub_vision({...}) 然后再发请求。"""
    state = {"payload": {}}
    monkeypatch.setattr(
        vision, "classify_from_bytes", lambda raw, mime: dict(state["payload"])
    )

    def _set(payload):
        state["payload"] = payload

    return _set


def _cat_payload(**over):
    base = {
        "species": "猫",
        "breed": "英短",
        "size": "中型",
        "species_code": "cat",
        "size_code": "medium",
        "body_condition": "正常",
        "coat_condition": "毛发枯燥",
        "health_notes": "多喝水",
        "confidence": 0.9,
        "_mode": "vlm",
    }
    base.update(over)
    return base


class Test识别接口:
    def test_未登录被拒(self, client):
        r = client.post(
            "/api/vision/classify",
            files={"file": ("pet.jpg", io.BytesIO(JPEG), "image/jpeg")},
        )
        assert r.status_code == 401

    def test_非图片类型被拒(self, client, auth_headers):
        r = client.post(
            "/api/vision/classify",
            files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_空文件被拒(self, client, auth_headers):
        r = client.post(
            "/api/vision/classify",
            files={"file": ("a.jpg", io.BytesIO(b""), "image/jpeg")},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_识别成功返回档位与落盘路径(self, client, auth_headers, stub_vision):
        stub_vision(_cat_payload())
        r = _post_image(client, auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["grade"] == "high"
        assert d["grade_cn"] == "高"
        assert d["can_save"] is True
        assert d["image_path"]  # 图片已落盘，供确认建档时复用

    def test_低置信仍允许建档(self, client, auth_headers, stub_vision):
        """低置信不挡用户——只降档，后续转人工确认。"""
        stub_vision(_cat_payload(confidence=0.3))
        d = _post_image(client, auth_headers).json()
        assert d["grade"] == "low"
        assert d["can_save"] is True

    def test_非宠物拒识且不落盘(self, client, auth_headers, stub_vision):
        stub_vision(
            {
                "species": "兔子",
                "species_code": "other",
                "confidence": 0.99,
                "_mode": "rejected",
                "rejected": True,
                "reject_reason": "识别结果并非宠物（物种：兔子），请上传猫/狗照片",
            }
        )
        d = _post_image(client, auth_headers).json()
        assert d["rejected"] is True
        assert d["can_save"] is False
        assert d["image_path"] is None


class Test建档与增删查:
    def test_建档成功且字段正确(self, client, auth_headers):
        r = client.post(
            "/api/pets",
            json={"name": "小黑", "species": "狗", "breed": "金毛",
                  "size": "大型", "confidence": 0.8},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["name"] == "小黑"
        assert d["species_code"] == "dog"
        assert d["size_code"] == "large"
        assert d["confidence_grade"] == "high"
        assert d["review_status"] == "auto"

    def test_低置信档案进待确认(self, client, auth_headers):
        r = client.post(
            "/api/pets", json={"species": "猫", "confidence": 0.2}, headers=auth_headers
        )
        assert r.json()["review_status"] == "pending"

    def test_档位由服务端重算不采信请求体(self, client, auth_headers):
        """契约里没有 grade 字段，前端硬塞也无效——防止把低置信"洗"成高档。"""
        r = client.post(
            "/api/pets",
            json={"species": "猫", "confidence": 0.1, "confidence_grade": "high"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["confidence_grade"] == "low"

    def test_未登录不能建档(self, client):
        assert client.post("/api/pets", json={"species": "猫"}).status_code == 401

    def test_列表返回自己的档案(self, client, auth_headers):
        client.post("/api/pets", json={"species": "猫", "confidence": 0.8},
                    headers=auth_headers)
        r = client.get("/api/pets", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_删除自己的档案(self, client, auth_headers):
        pid = client.post("/api/pets", json={"species": "猫", "confidence": 0.8},
                          headers=auth_headers).json()["id"]
        assert client.delete(f"/api/pets/{pid}", headers=auth_headers).status_code == 204
        assert client.get("/api/pets", headers=auth_headers).json() == []

    def test_删除不存在的档案返回404(self, client, auth_headers):
        assert client.delete("/api/pets/99999", headers=auth_headers).status_code == 404

    def test_伪造的图片路径被丢弃(self, client, auth_headers):
        """前端回传的 image_path 不可信，不在本人目录下的一律丢掉。"""
        r = client.post(
            "/api/pets",
            json={"species": "猫", "confidence": 0.9,
                  "image_path": "../../../etc/passwd"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["image_path"] is None


class Test用户隔离:
    def _headers(self, client, make_user, email):
        user, pw = make_user(email=email, username=email.split("@")[0])
        r = client.post("/api/login", json={"email": email, "password": pw})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_看不到别人的档案(self, client, make_user):
        a = self._headers(client, make_user, "a@test.com")
        b = self._headers(client, make_user, "b@test.com")
        client.post("/api/pets", json={"species": "猫", "confidence": 0.9}, headers=a)

        assert len(client.get("/api/pets", headers=a).json()) == 1
        assert client.get("/api/pets", headers=b).json() == []

    def test_删不掉别人的档案(self, client, make_user):
        a = self._headers(client, make_user, "a@test.com")
        b = self._headers(client, make_user, "b@test.com")
        pid = client.post(
            "/api/pets", json={"species": "猫", "confidence": 0.9}, headers=a
        ).json()["id"]

        # b 删除 a 的档案：接口返回 404（而不是 403，避免泄露"该 id 存在"）
        assert client.delete(f"/api/pets/{pid}", headers=b).status_code == 404
        # a 的档案仍在
        assert len(client.get("/api/pets", headers=a).json()) == 1
