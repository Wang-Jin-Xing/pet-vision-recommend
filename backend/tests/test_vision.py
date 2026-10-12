# -*- coding: utf-8 -*-
"""视觉识别模块测试：三层鲁棒解析 + 双层拒识 + 多模型降级链。

**重要**：项目根 .env 里可能配了真实的 LLM_API_KEY，conftest 不会清掉它。
因此凡是要走「无 Key」分支的用例，都必须显式 monkeypatch 成空串，
否则会真的发出网络请求。
"""
import pytest

from agents import vision


# ------------------------------------------------------------------
# 一、三层鲁棒解析：模型不按格式输出时，逐层兜住
# ------------------------------------------------------------------
class Test三层鲁棒解析:
    def test_第一层_剥掉代码块(self):
        assert vision._extract_json('```json\n{"species": "猫"}\n```') == {"species": "猫"}

    def test_第二层_剪掉前后废话(self):
        got = vision._extract_json('我觉得这是：{"species": "猫"} 仅供参考')
        assert got == {"species": "猫"}

    def test_第三层_无花括号时逐行抠(self):
        got = vision._extract_json("species: 猫\nbreed: 英短")
        assert got == {"species": "猫", "breed": "英短"}

    def test_完全跑题时返回None(self):
        assert vision._extract_json("今天天气不错，猫咪看起来很健康，建议多晒太阳。") is None

    def test_三种畸形输入全部兜住(self):
        """对齐 PetSight 的实测基线：3 种「不老实但还在说正事」的输出 3/3 全部可解析。"""
        malformed = [
            '```json\n{"species": "猫", "breed": "英短"}\n```',
            '我认为是：{"species": "狗", "breed": "金毛"} 以上',
            "species: 猫\nbreed: 中华田园猫\nconfidence: 0.8",
        ]
        ok = [c for c in malformed if vision._extract_json(c)]
        assert len(ok) == 3

    def test_嵌套结构不会被截断(self):
        raw = '```json\n{"species": "狗", "health_notes": ["多喝水", "少盐"]}\n```'
        got = vision._extract_json(raw)
        assert got["health_notes"] == ["多喝水", "少盐"]


class Test字段标准化:
    def test_缺字段全部填默认值(self):
        n = vision._normalize({})
        assert n["species"] == "未知"
        assert n["breed"] == "未知"
        assert n["confidence"] == 0.0

    def test_health_notes列表转成一句话(self):
        n = vision._normalize({"health_notes": ["多喝水", "少盐"]})
        assert n["health_notes"] == "多喝水，少盐"

    def test_confidence是垃圾字符串时归零(self):
        assert vision._normalize({"confidence": "很高"})["confidence"] == 0.0

    def test_confidence为None时归零(self):
        assert vision._normalize({"confidence": None})["confidence"] == 0.0

    def test_空白字符串被替换为占位符(self):
        n = vision._normalize({"species": "   ", "coat_condition": ""})
        assert n["species"] == "未知"
        assert n["coat_condition"] == "——"


class Test物种判断:
    @pytest.mark.parametrize(
        "species,expected",
        [
            ("猫", True),
            ("中华田园犬", True),
            ("cat", True),
            ("Dog", True),
            ("feline", True),
            ("兔子", False),
            ("仓鼠", False),
            ("未知", False),
            ("", False),
        ],
    )
    def test_是否猫狗(self, species, expected):
        assert vision._looks_like_pet(species) is expected

    @pytest.mark.parametrize(
        "species,code",
        [
            # species 按提示词约束只会是 猫/狗/其他（或英文），这里测它的真实取值域。
            # 注意：品种名（如"金毛"）属于 breed 字段，不含"狗/犬"关键词时会归 other——
            # 这是已知边界，靠提示词约束 species 字段来规避。
            ("猫", "cat"),
            ("英短猫", "cat"),
            ("cat", "cat"),
            ("中华田园犬", "dog"),
            ("犬", "dog"),
            ("canine", "dog"),
            ("兔子", "other"),
            ("其他", "other"),
            ("golden retriever", "other"),
            ("未知", "other"),
        ],
    )
    def test_物种归一为结构化代码(self, species, code):
        assert vision._species_code(species) == code


# ------------------------------------------------------------------
# 二、双层拒识
# ------------------------------------------------------------------
class Test拒识:
    def test_非宠物直接拒(self):
        reason = vision._should_reject({"species": "兔子", "confidence": 0.99})
        assert reason and "并非宠物" in reason

    def test_物种缺失提示重传(self):
        reason = vision._should_reject({"species": "未知", "confidence": 0.9})
        assert reason and "未能识别出宠物" in reason

    def test_低置信不在这层拒(self):
        """低置信不挡用户——留给后续降档 + 转人工（这是相对 PetSight 原版的设计改动）。"""
        assert vision._should_reject({"species": "猫", "confidence": 0.1}) == ""

    def test_正常结果不拒(self):
        assert vision._should_reject({"species": "猫", "confidence": 0.9}) == ""


# ------------------------------------------------------------------
# 三、凭据解析（本项目对 PetSight 原版的改进点）
# ------------------------------------------------------------------
class Test凭据解析:
    def test_留空时复用LLM凭据(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "llm-key")
        monkeypatch.setattr(vision.settings, "LLM_BASE_URL", "https://a.example/v1/")
        monkeypatch.setattr(vision.settings, "VLM_API_KEY", "")
        monkeypatch.setattr(vision.settings, "VLM_BASE_URL", "")
        key, base = vision._vlm_credentials()
        assert key == "llm-key"
        assert base == "https://a.example/v1"  # 末尾斜杠被规整掉

    def test_填了就用自己的凭据(self, monkeypatch):
        """换别家视觉模型时只改配置——这正是 PetSight 原架构做不到的。"""
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "llm-key")
        monkeypatch.setattr(vision.settings, "VLM_API_KEY", "vlm-key")
        monkeypatch.setattr(vision.settings, "VLM_BASE_URL", "https://b.example/v1")
        key, base = vision._vlm_credentials()
        assert key == "vlm-key"
        assert base == "https://b.example/v1"


# ------------------------------------------------------------------
# 四、模型调用链（monkeypatch，不联网）
# ------------------------------------------------------------------
class Test调用链:
    def test_无Key走本地兜底(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "")
        monkeypatch.setattr(vision.settings, "VLM_API_KEY", "")
        r = vision.classify_pet_image("FAKE")
        assert r["_mode"] == "local_fallback"
        assert r["confidence"] == 0.0
        # 兜底也必须返回完整字段，下游不会拿到空值
        for f in ("species", "breed", "body_condition", "coat_condition", "health_notes"):
            assert r.get(f)

    def test_主模型失败会依次试备用模型(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "k")
        monkeypatch.setattr(vision.settings, "VLM_MODEL", "primary")
        monkeypatch.setattr(vision.settings, "VLM_FALLBACK_MODELS", "backup")
        calls = []

        def fake_one(image_data_url, model, key, base):
            calls.append(model)
            if model == "primary":
                return None  # 主模型吐出无法解析的内容
            return {"species": "狗", "breed": "金毛", "confidence": 0.9}

        monkeypatch.setattr(vision, "_call_one_model", fake_one)
        r = vision.classify_pet_image("FAKE")
        assert calls == ["primary", "backup"]
        assert r["_mode"] == "vlm"
        assert r["breed"] == "金毛"

    def test_模型全失败时降级但不抛异常(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "k")
        monkeypatch.setattr(vision, "_call_vlm_with_fallback", lambda u: {"_error": "boom"})
        r = vision.classify_pet_image("FAKE")
        assert r["_mode"] == "vlm_error"
        assert r["species"] == "未知"  # 仍然是一套完整字段

    def test_拒识结果带原因且不抛异常(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "k")
        monkeypatch.setattr(
            vision,
            "_call_vlm_with_fallback",
            lambda u: {"species": "兔子", "confidence": 0.95},
        )
        r = vision.classify_pet_image("FAKE")
        assert r["_mode"] == "rejected"
        assert r["rejected"] is True
        assert "并非宠物" in r["reject_reason"]

    def test_模型列表去重且保序(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "VLM_MODEL", "a")
        monkeypatch.setattr(vision.settings, "VLM_FALLBACK_MODELS", "a, b  c")
        assert vision._model_list() == ["a", "b", "c"]

    def test_字节入口会做base64编码(self, monkeypatch):
        monkeypatch.setattr(vision.settings, "LLM_API_KEY", "k")
        seen = {}

        def fake(url):
            seen["url"] = url
            return {"species": "猫", "confidence": 0.9}

        monkeypatch.setattr(vision, "_call_vlm_with_fallback", fake)
        vision.classify_from_bytes(b"\xff\xd8\xff", "image/jpeg")
        assert seen["url"].startswith("data:image/jpeg;base64,")
