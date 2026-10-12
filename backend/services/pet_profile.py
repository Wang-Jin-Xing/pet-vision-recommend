"""宠物档案服务：识别结果的落库、查询，以及「置信度 → 档位」的判定。

把业务逻辑集中在服务层，路由只做参数校验与鉴权，判定规则单独可测。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

import models
from config import settings

# 各档位的机器可读名
GRADE_HIGH = "high"
GRADE_MEDIUM = "medium"
GRADE_LOW = "low"

GRADE_CN = {GRADE_HIGH: "高", GRADE_MEDIUM: "中", GRADE_LOW: "低"}

# 图片扩展名白名单（同时用于入库存后缀）
MIME_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def grade_confidence(confidence: float, species_code: str) -> str:
    """把识别置信度判成三档——这是本项目「可信度分级」的判定中心。

    规则（阈值来自配置，不写死）：
      - 没认出是猫/狗            → low   （连大方向都不对，不能用）
      - confidence >= HIGH       → high  （可精确到品种）
      - MIN <= confidence < HIGH → medium（只能确定猫/狗，不能确定品种）
      - confidence < MIN         → low   （不确定到不可用）
    """
    if species_code not in ("cat", "dog"):
        return GRADE_LOW
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return GRADE_LOW
    if c >= settings.CONFIDENCE_HIGH:
        return GRADE_HIGH
    if c >= settings.MIN_CONFIDENCE:
        return GRADE_MEDIUM
    return GRADE_LOW


def review_status_for(grade: str) -> str:
    """低档档案进人工确认队列；中高档自动通过。"""
    return "pending" if grade == GRADE_LOW else "auto"


def save_pet_image(raw: bytes, user_id: int, mime: str) -> str:
    """把图片存到 PET_IMAGE_DIR/<user_id>/<uuid><后缀>，返回存储路径。

    按 user_id 分目录存放，不做公开静态托管——档案只能被本人访问。
    """
    suffix = MIME_SUFFIX.get((mime or "").lower(), ".jpg")
    root = Path(settings.PET_IMAGE_DIR)
    user_dir = root / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(raw)
    return path.as_posix()


def build_profile_fields(vision_result: dict) -> dict:
    """把视觉模块的输出整理成建档字段（含归档档位与审核状态）。"""
    species_code = _species_code(vision_result)
    confidence = _safe_float(vision_result.get("confidence"))
    grade = grade_confidence(confidence, species_code)
    return {
        "species": str(vision_result.get("species", "未知")),
        "breed": str(vision_result.get("breed", "未知")),
        "body_condition": str(vision_result.get("body_condition", "——")),
        "coat_condition": str(vision_result.get("coat_condition", "——")),
        "health_notes": str(vision_result.get("health_notes", "——")),
        "species_code": species_code,
        "size_code": _size_code(vision_result),
        "confidence": confidence,
        "confidence_grade": grade,
        "review_status": review_status_for(grade),
    }


def create_profile(
    db: Session,
    user_id: int,
    name: str,
    vision_result: dict,
    image_path: Optional[str] = None,
) -> models.PetProfile:
    """建档：由一次识别结果生成一条档案。"""
    fields = build_profile_fields(vision_result)
    profile = models.PetProfile(
        user_id=user_id,
        name=(name or "我的宠物").strip() or "我的宠物",
        image_path=image_path,
        **fields,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def list_profiles(db: Session, user_id: int) -> list[models.PetProfile]:
    """某用户的全部档案，新→旧。"""
    return (
        db.query(models.PetProfile)
        .filter(models.PetProfile.user_id == user_id)
        .order_by(models.PetProfile.id.desc())
        .all()
    )


def get_owned_profile(
    db: Session, user_id: int, profile_id: int
) -> Optional[models.PetProfile]:
    """取自己的档案；不是自己的返回 None（避免越权读取）。"""
    return (
        db.query(models.PetProfile)
        .filter(
            models.PetProfile.id == profile_id,
            models.PetProfile.user_id == user_id,
        )
        .first()
    )


def delete_profile(db: Session, user_id: int, profile_id: int) -> bool:
    """删除自己的档案；不存在或非本人返回 False。"""
    profile = get_owned_profile(db, user_id, profile_id)
    if profile is None:
        return False
    db.delete(profile)
    db.commit()
    return True


def to_workflow_profile(profile: models.PetProfile) -> dict:
    """把档案记录转成工作流 state 里的 `pet_profile` 结构。

    结构与 vision_agent_node 产出的保持一致，使"选用已有档案"和"现场识别照片"
    两条路对后续节点完全等价——后续节点不需要知道这次信息是从哪来的。
    """
    return {
        "species": profile.species,
        "species_code": profile.species_code,
        "breed": profile.breed,
        "size": profile.size_code,
        "size_code": profile.size_code,
        "body_condition": profile.body_condition,
        "coat_condition": profile.coat_condition,
        "health_notes": profile.health_notes,
        "confidence": profile.confidence,
        "rejected": False,
        "reject_reason": "",
        "mode": "profile",
    }


# ------------------------------------------------------------------
# 内部小工具
# ------------------------------------------------------------------
def _species_code(result: dict) -> str:
    """优先用视觉模块给出的结构化 code，缺失时按物种原文兜底推断。"""
    code = str(result.get("species_code") or "").strip()
    if code in ("cat", "dog", "other"):
        return code
    species = str(result.get("species", "")).lower()
    if "猫" in species or "cat" in species or "feline" in species:
        return "cat"
    if "狗" in species or "犬" in species or "dog" in species or "canine" in species:
        return "dog"
    return "other"


def _size_code(result: dict) -> str:
    """优先用视觉模块给出的体型 code，缺失时按体型原文兜底推断。"""
    code = str(result.get("size_code") or "").strip()
    if code in ("small", "medium", "large", "unknown"):
        return code
    low = str(result.get("size", "")).lower()
    if any(k in low for k in ("小型", "mini", "small", "toy")):
        return "small"
    if any(k in low for k in ("中型", "medium")):
        return "medium"
    if any(k in low for k in ("大型", "巨型", "large", "giant")):
        return "large"
    return "unknown"


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
