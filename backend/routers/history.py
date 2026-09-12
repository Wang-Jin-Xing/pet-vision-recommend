"""历史对话路由（全部需要登录）：对话列表与按 thread_id 查询详情。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """获取当前用户的全部对话（最近更新在前），每条对话内嵌完整消息列表。"""
    return (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == current_user.id)
        .order_by(models.Conversation.updated_at.desc())
        .all()
    )


@router.get("/{thread_id}", response_model=schemas.ConversationOut)
def get_conversation(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """按 thread_id 获取单个对话详情（只能查看属于自己的对话）。"""
    conversation = (
        db.query(models.Conversation)
        .filter(models.Conversation.thread_id == thread_id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该对话")
    return conversation
