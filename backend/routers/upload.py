"""文档上传路由：保存文件 -> 写库 -> 切块写入 ChromaDB 知识库。"""
import logging
import os
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from agents.tools import ingest_text
from auth import get_current_user
from config import settings
from database import get_db

router = APIRouter()

logger = logging.getLogger("petpals")

ALLOWED_SUFFIXES = (".txt", ".md")

# 文件名只保留中文、字母数字、下划线/连字符/点/括号/空格；
# 其余字符（含路径分隔符、盘符冒号、控制字符等）一律剔除
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _safe_filename(raw_name: str) -> str:
    """清洗用户上传文件名，防止路径穿越与任意文件覆盖。

    - 去掉任何目录部分（兼容 Windows 反斜杠与盘符）
    - 剔除危险字符与控制字符
    - 不允许以点开头（避免 ".env" 类隐藏文件）
    """
    name = raw_name.replace("\\", "/").split("/")[-1].strip()
    name = _UNSAFE_FILENAME.sub("_", name)
    name = name.lstrip(".")
    return name[:200]


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """上传文本文档并加入 RAG 知识库（目前支持 txt / md，单文件不超过 2 MB）。"""
    safe_name = _safe_filename(file.filename or "")
    if not safe_name:
        raise HTTPException(status_code=400, detail="文件名不合法")

    suffix = os.path.splitext(safe_name)[1].lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="目前仅支持 txt / md 文本文档")

    content_bytes = await file.read()
    if len(content_bytes) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，单文件上限 {settings.MAX_UPLOAD_BYTES // 1024} KB",
        )

    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件必须为 UTF-8 编码的文本")
    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容不能为空")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    # 先建记录拿到 id，落盘文件名带 id 前缀，避免同名文件互相覆盖
    document = models.Document(
        user_id=current_user.id,
        filename=safe_name,
        file_path="",
        chunks=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    stored_name = f"{document.id}-{safe_name}"
    file_path = os.path.join(settings.UPLOAD_DIR, stored_name)
    try:
        with open(file_path, "wb") as f:
            f.write(content_bytes)
    except OSError as exc:
        logger.exception("保存上传文件失败：%s", exc)
        db.delete(document)
        db.commit()
        raise HTTPException(status_code=500, detail="文件保存失败，请稍后重试")

    # 切块并写入向量库（失败不影响文件上传主流程），再把切块数回写文档记录
    try:
        chunk_count = ingest_text(document.id, text, safe_name)
    except Exception as exc:
        logger.exception("写入向量库失败：%s", exc)
        chunk_count = 0

    document.file_path = file_path
    document.chunks = chunk_count
    db.commit()

    return {
        "message": "上传成功",
        "document_id": document.id,
        "chunks": chunk_count,
    }


@router.get("/documents", response_model=list[schemas.DocumentOut])
def list_my_documents(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """查看当前用户上传过的文档。"""
    return (
        db.query(models.Document)
        .filter(models.Document.user_id == current_user.id)
        .order_by(models.Document.created_at.desc())
        .all()
    )
