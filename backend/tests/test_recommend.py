# -*- coding: utf-8 -*-
"""按宠物档案筛选商品的测试：**三档行为必须不同**，且筛空必须回退。"""
from services import recommend


def _p(pid, name, species, size, tags):
    return {"id": pid, "name": name, "species": species, "size": size, "tags": tags}


DOG_FOOD = _p(1, "成犬狗粮", "dog", "all", [])
CAT_FOOD = _p(2, "深海鱼猫粮", "cat", "all", ["美毛"])
CAT_TOY = _p(3, "羽毛逗猫棒", "cat", "all", ["互动"])
SHAMPOO = _p(4, "温和沐浴露", "both", "all", ["低敏"])
BONE = _p(5, "洁齿磨牙骨", "dog", "medium", ["洁齿"])
CAT_LITTER = _p(6, "结团猫砂", "cat", "all", ["除臭"]) 

ALL = [DOG_FOOD, CAT_FOOD, CAT_TOY, SHAMPOO, BONE, CAT_LITTER]


class Test体型匹配:
    def test_中号商品小型宠物可用(self):
        """磨牙骨标 medium = 中小型犬可用，小型犬应该也能用。"""
        assert recommend.size_ok("small", "medium") is True

    def test_大号宠物用不了中号商品(self):
        assert recommend.size_ok("large", "medium") is False

    def test_通用尺寸人人可用(self):
        assert recommend.size_ok("large", "all") is True

    def test_体型未知时不限制(self):
        """识别不出体型时宁可多推，也别误杀。"""
        assert recommend.size_ok("unknown", "small") is True


class Test三档行为:
    def test_低档完全不使用档案(self):
        out, note = recommend.filter_by_profile(ALL, {"species_code": "cat"}, "low")
        assert out == ALL
        assert note == ""

    def test_中档只按物种筛(self):
        out, note = recommend.filter_by_profile(
            ALL,
            {"species_code": "cat", "size_code": "small", "coat_condition": "毛发枯燥"},
            "medium",
        )
        names = {p["name"] for p in out}
        assert names == {"深海鱼猫粮", "羽毛逗猫棒", "温和沐浴露", "结团猫砂"}
        assert "不区分品种" in note

    def test_高档加体型与健康诉求(self):
        out, note = recommend.filter_by_profile(
            ALL,
            {"species_code": "cat", "size_code": "small", "coat_condition": "毛发枯燥"},
            "high",
        )
        # 猫商品里只有猫粮带「美毛」标签
        assert [p["name"] for p in out] == ["深海鱼猫粮"]
        assert "美毛" in note

    def test_高档无诉求命中时退回物种级(self):
        out, _ = recommend.filter_by_profile(
            ALL, {"species_code": "cat", "size_code": "small"}, "high"
        )
        assert {p["name"] for p in out} == {
            "深海鱼猫粮", "羽毛逗猫棒", "温和沐浴露", "结团猫砂"
        }

    def test_中档与高档结果不同(self):
        """这是三档设计的核心：档位不同，推荐结果必须真的不一样。"""
        profile = {"species_code": "cat", "size_code": "small", "coat_condition": "毛发枯燥"}
        mid, _ = recommend.filter_by_profile(ALL, profile, "medium")
        high, _ = recommend.filter_by_profile(ALL, profile, "high")
        assert len(high) < len(mid)

    def test_物种筛空时回退不返回空(self):
        out, note = recommend.filter_by_profile(
            [DOG_FOOD, BONE], {"species_code": "cat"}, "medium"
        )
        assert out == [DOG_FOOD, BONE]
        assert note == ""

    def test_物种不可用时不筛(self):
        out, note = recommend.filter_by_profile(ALL, {"species_code": "other"}, "high")
        assert out == ALL
        assert note == ""

    def test_空商品列表安全(self):
        assert recommend.filter_by_profile([], {"species_code": "cat"}, "high") == ([], "")

    def test_无档案时不筛(self):
        out, note = recommend.filter_by_profile(ALL, None, "high")
        assert out == ALL


class Test诉求标签映射:
    def test_毛发枯燥映射到美毛(self):
        assert "美毛" in recommend.desired_tags({"coat_condition": "毛发枯燥"})

    def test_口气重映射到洁齿(self):
        assert "洁齿" in recommend.desired_tags({"health_notes": "有牙垢，口气比较重"})

    def test_健康状态不产生标签(self):
        assert recommend.desired_tags({"coat_condition": "健康顺滑"}) == set()
