"""商品路由：列表（分类筛选/关键字搜索/分页）、详情、创建（管理员）。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from auth import require_admin
from database import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.ProductOut])
def list_products(
    category: Optional[str] = Query(default=None, description="按商品分类精确筛选"),
    keyword: Optional[str] = Query(default=None, description="在名称/描述中模糊搜索"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数（分页偏移）"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数，1-100"),
    db: Session = Depends(get_db),
):
    """商品列表：支持 category 筛选、keyword 搜索与 skip/limit 分页。"""
    query = db.query(models.Product)

    if category:
        query = query.filter(models.Product.category == category)

    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                models.Product.name.like(like),
                models.Product.description.like(like),
            )
        )

    return query.order_by(models.Product.id).offset(skip).limit(limit).all()


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """商品详情，不存在时返回 404。"""
    product = db.get(models.Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    """创建商品（需要管理员权限）：未登录 401，普通用户 403。"""
    if payload.price < 0:
        raise HTTPException(status_code=400, detail="商品价格不能为负数")
    if payload.stock < 0:
        raise HTTPException(status_code=400, detail="商品库存不能为负数")

    product = models.Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
