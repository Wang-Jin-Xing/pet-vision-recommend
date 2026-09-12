"""订单路由（均需登录）：下单、我的订单列表、订单详情、更新订单状态。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter()

# 允许的订单状态流转值
ALLOWED_ORDER_STATUS = ("pending", "paid", "shipped", "delivered")


def _get_owned_order(
    order_id: int,
    db: Session,
    current_user: models.User,
) -> models.Order:
    """取出订单并校验归属：不存在 404，非本人且非管理员 403。"""
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权操作该订单")
    return order


@router.post("", response_model=schemas.OrderOut, status_code=201)
def create_order(
    payload: schemas.OrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """根据购物车商品列表创建订单，校验商品存在性与库存，扣减库存并记录单价快照。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="订单不能为空")

    order = models.Order(user_id=current_user.id, status="pending", total=0.0)
    total = 0.0

    for item in payload.items:
        product = db.get(models.Product, item.product_id)
        if product is None:
            # 未提交的库存变动随异常回滚
            db.rollback()
            raise HTTPException(status_code=404, detail=f"商品 {item.product_id} 不存在")
        if product.stock < item.quantity:
            db.rollback()
            raise HTTPException(
                status_code=400, detail=f"商品「{product.name}」库存不足"
            )

        # 扣减库存，记录下单时单价
        product.stock -= item.quantity
        order.items.append(
            models.OrderItem(
                product_id=product.id,
                quantity=item.quantity,
                price=product.price,
            )
        )
        total += product.price * item.quantity

    order.total = round(total, 2)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("", response_model=list[schemas.OrderOut])
def list_my_orders(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """查看当前用户的全部订单（新订单在前）。"""
    return (
        db.query(models.Order)
        .filter(models.Order.user_id == current_user.id)
        .order_by(models.Order.created_at.desc())
        .all()
    )


@router.get("/{order_id}", response_model=schemas.OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """订单详情：本人或管理员可查看。"""
    return _get_owned_order(order_id, db, current_user)


@router.patch("/{order_id}/status", response_model=schemas.OrderOut)
def update_order_status(
    order_id: int,
    payload: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """更新订单状态（本人或管理员）：非法状态 400，订单不存在 404，无权操作 403。"""
    new_status = payload.status.strip().lower()
    if new_status not in ALLOWED_ORDER_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"非法订单状态，允许值：{', '.join(ALLOWED_ORDER_STATUS)}",
        )

    order = _get_owned_order(order_id, db, current_user)

    if order.status == "delivered":
        raise HTTPException(status_code=400, detail="订单已签收，状态不可再修改")
    if order.status == new_status:
        raise HTTPException(status_code=400, detail=f"订单已是 {new_status} 状态")

    order.status = new_status
    db.commit()
    db.refresh(order)
    return order
