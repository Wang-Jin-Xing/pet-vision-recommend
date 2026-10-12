# -*- coding: utf-8 -*-
"""置信度三档判定测试——本项目「可信度分级」的判定中心，边界必须精确。"""
import pytest

from config import settings
from services import pet_profile


class Test三档判定:
    @pytest.mark.parametrize(
        "confidence,expected",
        [
            (0.0, "low"),
            (0.49, "low"),
            (0.50, "medium"),  # 边界：恰好等于下限 → 中档
            (0.66, "medium"),
            (0.74, "medium"),
            (0.75, "high"),  # 边界：恰好等于上限 → 高档
            (0.99, "high"),
            (1.0, "high"),
        ],
    )
    def test_猫在各置信度下的档位(self, confidence, expected):
        assert pet_profile.grade_confidence(confidence, "cat") == expected

    def test_狗适用同一规则(self):
        assert pet_profile.grade_confidence(0.8, "dog") == "high"

    def test_没认出物种时一律低档(self):
        """即便模型自报置信度 0.99，只要不是猫/狗，也不能当高档用。"""
        assert pet_profile.grade_confidence(0.99, "other") == "low"

    def test_置信度为非法值时归低档(self):
        assert pet_profile.grade_confidence("很高", "cat") == "low"
        assert pet_profile.grade_confidence(None, "cat") == "low"

    def test_阈值来自配置而非写死(self, monkeypatch):
        monkeypatch.setattr(settings, "CONFIDENCE_HIGH", 0.9)
        assert pet_profile.grade_confidence(0.85, "cat") == "medium"
        assert pet_profile.grade_confidence(0.9, "cat") == "high"

        monkeypatch.setattr(settings, "MIN_CONFIDENCE", 0.3)
        assert pet_profile.grade_confidence(0.35, "cat") == "medium"
        assert pet_profile.grade_confidence(0.2, "cat") == "low"


class Test审核状态:
    def test_低档进人工确认队列(self):
        assert pet_profile.review_status_for("low") == "pending"

    def test_中高档自动通过(self):
        assert pet_profile.review_status_for("medium") == "auto"
        assert pet_profile.review_status_for("high") == "auto"


class Test建档字段整理:
    def test_从识别结果生成完整字段(self):
        fields = pet_profile.build_profile_fields(
            {
                "species": "猫",
                "breed": "英短",
                "size": "中型",
                "confidence": 0.9,
                "coat_condition": "毛发枯燥",
            }
        )
        assert fields["species_code"] == "cat"
        assert fields["size_code"] == "medium"
        assert fields["confidence_grade"] == "high"
        assert fields["review_status"] == "auto"

    def test_低置信档案自动转待确认(self):
        fields = pet_profile.build_profile_fields({"species": "狗", "confidence": 0.2})
        assert fields["confidence_grade"] == "low"
        assert fields["review_status"] == "pending"

    def test_缺失字段有兜底(self):
        fields = pet_profile.build_profile_fields({"species": "猫"})
        assert fields["breed"] == "未知"
        assert fields["confidence"] == 0.0
        assert fields["size_code"] == "unknown"
