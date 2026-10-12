"""按宠物档案筛选商品——本项目「可信度分级」落成推荐行为的地方。

同样是"给这只宠物推荐商品"，档位不同、做法就不同：

| 档位 | 依据 | 为什么这样定 |
|---|---|---|
| 高 ≥0.75 | 物种 + 体型 + 健康诉求，全量匹配 | 识别可信，敢精确到品种级条件 |
| 中 0.5~0.75 | **只按物种** | 大方向可信、细节不可信。推错具体品种的商品，用户当场就能发现 |
| 低 <0.5 | **完全不用档案** | 识别不可信，宁可不推 |

设计上的一条硬约束：**任何一步筛空都回退，绝不返回空列表**。
推荐结果为空比推荐得不够准更糟——用户会觉得"你这功能坏了"。
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

GRADE_HIGH = "high"
GRADE_MEDIUM = "medium"

# 体型等级：商品 size 语义是"适配体型的**上限**"（如磨牙骨标 medium = 中小型犬可用）
_SIZE_RANK = {"small": 1, "medium": 2, "large": 3, "all": 3}

# 识别出的非结构化描述 → 商品标签。
# 这一步是"把模型说的自然语言，翻译成商品表能匹配的结构化标签"。
_TAG_HINTS = {
    "美毛": ("毛", "掉毛", "枯燥", "干枯", "秃", "皮屑"),
    "洁齿": ("牙", "口臭", "口气", "牙垢", "结石"),
    "低敏": ("敏感", "过敏", "瘙痒", "皮肤"),
    "除臭": ("臭", "异味", "气味"),
    "互动": ("互动", "玩具", "陪玩", "无聊"),
}


def size_ok(pet_size: str, product_size: str) -> bool:
    """宠物能不能用这个尺寸的商品：宠物不超过商品上限即可。

    体型未知时**不限制**（返回 True）——宁可多推，也不要因为识别不出体型就误杀。
    """
    if pet_size in (None, "", "unknown"):
        return True
    return _SIZE_RANK.get(pet_size, 3) <= _SIZE_RANK.get(product_size or "all", 3)


def species_ok(product_species: str, pet_species: str) -> bool:
    """商品适用物种是否覆盖该宠物（both=犬猫通用）。"""
    return (product_species or "") in (pet_species, "both")


def desired_tags(profile: dict) -> set:
    """从识别结果里提取"健康诉求"，映射成商品标签集合。"""
    text = " ".join(
        str(profile.get(k, ""))
        for k in ("coat_condition", "body_condition", "health_notes")
    )
    return {tag for tag, kws in _TAG_HINTS.items() if any(k in text for k in kws)}


def filter_by_profile(
    products: List[dict],
    profile: dict,
    grade: str,
) -> Tuple[List[dict], str]:
    """按档位筛选商品。返回 (筛选后的商品, 给用户看的说明)。"""
    if not products:
        return products, ""
    if not profile or grade not in (GRADE_HIGH, GRADE_MEDIUM):
        return products, ""

    species = profile.get("species_code", "")
    if species not in ("cat", "dog"):
        return products, ""  # 物种不可用，不筛

    # ---- 第一层：物种（中档只做到这里）----
    by_species = [p for p in products if species_ok(p.get("species"), species)]
    if not by_species:
        return products, ""  # 筛空了 → 回退，不用档案
    if grade == GRADE_MEDIUM:
        name = "猫" if species == "cat" else "狗"
        return by_species, f"已按识别结果只筛选适合「{name}」的商品（识别置信度中等，不区分品种）"

    # ---- 第二层（仅高档）：体型 ----
    pet_size = profile.get("size_code", "unknown")
    by_size = [p for p in by_species if size_ok(pet_size, p.get("size"))]
    if not by_size:
        by_size = by_species  # 体型筛空 → 退回物种级

    # ---- 第三层（仅高档）：健康诉求标签 ----
    tags = desired_tags(profile)
    out = by_size
    hit_tags: set = set()
    if tags:
        prefer = [p for p in by_size if tags & set(p.get("tags") or [])]
        if prefer:  # 有命中才收窄；没命中就不拿标签当硬条件，避免筛空
            out, hit_tags = prefer, tags & {
                t for p in prefer for t in (p.get("tags") or [])
            }

    bits = []
    bits.append("猫" if species == "cat" else "狗")
    if pet_size not in ("unknown", "", None):
        bits.append({"small": "小型", "medium": "中型", "large": "大型"}.get(pet_size, ""))
    if hit_tags:
        bits.append("、".join(sorted(hit_tags)))
    detail = "·".join(b for b in bits if b)
    return out, f"已按识别结果精确筛选（{detail}），识别置信度高"
