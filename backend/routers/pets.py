"""宠物档案路由：照片识别 + 档案增删查。

- POST   /api/vision/classify  上传照片 → 识别 → 返回结果与档位（**不入库**，等用户确认）
- POST   /api/pets             确认建档
- GET    /api/pets             我的档案列表
- DELETE /api/pets/{pet_id}    删除档案

档案按 user_id 隔离——只能看/改/删自己的。
识别的重活交给 agents/vision.py，档位判定交给 services/pet_profile.py，
本层只做鉴权、入参校验与落库编排。
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from agents import vision
from auth import get_current_user
from config import settings
from database import get_db
from services import pet_profile as profile_service

router = APIRouter()


def _own_image_path(user_id: int, image_path: Optional[str]) -> Optional[str]:
    """校验图片路径确实落在**本人**的目录下，不合法则丢弃。

    前端回传的 image_path 不可信：不校验就等于把「写任意路径」的权限交出去了。
    """
    if not image_path:
        return None
    try:
        root = Path(settings.PET_IMAGE_DIR).resolve()
        p = Path(image_path).resolve()
        p.relative_to(root)  # 不在图片根目录下 → 抛 ValueError
    except (ValueError, OSError):
        return None
    if p.parent.name != str(user_id):  # 不在自己的子目录下 → 拒绝
        return None
    return image_path


@router.post("/vision/classify", response_model=schemas.VisionResult, tags=["宠物档案"])
async def classify_pet_photo(
    file: UploadFile = File(..., description="宠物照片（JPG / PNG / WEBP / GIF）"),
    current_user: models.User = Depends(get_current_user),
):
    """识别一张宠物照片，返回结构化结果与置信度档位。

    只识别、不建档：结果交给前端展示，用户确认（或修正）后再调 POST /api/pets。
    通过校验的图片会落盘，`image_path` 随结果返回，确认建档时原样回传，免得二次上传。
    """
    mime = (file.content_type or "").lower()
    if mime not in vision.ALLOWED_MIME:
        raise HTTPException(
            status_code=400, detail="仅支持 JPG / PNG / WEBP / GIF 格式的图片"
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(raw) > settings.MAX_IMAGE_BYTES:
        limit_mb = settings.MAX_IMAGE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"图片过大，请压缩到 {limit_mb} MB 以内")

    result = vision.classify_from_bytes(raw, mime)
    grade = profile_service.grade_confidence(
        result.get("confidence", 0.0), result.get("species_code", "other")
    )
    can_save = result.get("species_code") in ("cat", "dog")

    image_path = None
    if can_save:
        # 认不出 / 不是宠物的结果不落盘：用户本来就要换张图，留着只会攒垃圾
        image_path = profile_service.save_pet_image(raw, current_user.id, mime)

    return schemas.VisionResult(
        species=result.get("species", "未知"),
        breed=result.get("breed", "未知"),
        size=result.get("size", "不确定"),
        size_code=result.get("size_code", "unknown"),
        body_condition=result.get("body_condition", "——"),
        coat_condition=result.get("coat_condition", "——"),
        health_notes=result.get("health_notes", "——"),
        confidence=result.get("confidence", 0.0),
        mode=result.get("_mode", ""),
        rejected=bool(result.get("rejected")),
        reject_reason=result.get("reject_reason", ""),
        grade=grade,
        grade_cn=profile_service.GRADE_CN.get(grade, ""),
        can_save=can_save,
        image_path=image_path,
    )


@router.post(
    "/pets", response_model=schemas.PetProfileOut, status_code=201, tags=["宠物档案"]
)
def create_pet_profile(
    payload: schemas.PetProfileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """确认建档。

    档位与审核状态**由服务端重算**，不采信前端传来的档位——避免伪造一次识别结果
    就把低置信档案"洗"成高档、跳过人工确认。
    """
    result = {
        "species": payload.species,
        "breed": payload.breed,
        "size": payload.size,
        "body_condition": payload.body_condition,
        "coat_condition": payload.coat_condition,
        "health_notes": payload.health_notes,
        "confidence": payload.confidence,
    }
    return profile_service.create_profile(
        db,
        user_id=current_user.id,
        name=payload.name,
        vision_result=result,
        image_path=_own_image_path(current_user.id, payload.image_path),
    )


@router.get("/pets", response_model=list[schemas.PetProfileOut], tags=["宠物档案"])
def list_my_pet_profiles(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """我的宠物档案列表（只返回自己的）。"""
    return profile_service.list_profiles(db, current_user.id)


@router.delete("/pets/{pet_id}", status_code=204, tags=["宠物档案"])
def delete_pet_profile(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """删除自己的宠物档案；不是自己的或不存在 → 404。"""
    if not profile_service.delete_profile(db, current_user.id, pet_id):
        raise HTTPException(status_code=404, detail="档案不存在")
    return Response(status_code=204)
