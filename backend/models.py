"""ORM 数据模型（SQLAlchemy 2.0 风格：Mapped + mapped_column）。

包含：User / Product / Order / OrderItem / Document
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关联关系
    orders: Mapped[List["Order"]] = relationship(back_populates="user")
    documents: Mapped[List["Document"]] = relationship(back_populates="user")
    pet_profiles: Mapped[List["PetProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Product(Base):
    """商品表"""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    category: Mapped[str] = mapped_column(String(64), default="其他")
    # 适用对象，如：成犬 / 幼猫 / 全阶段（**展示文案**，给人看的）
    suitable: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # ↓ 适用条件的**结构化**版本（机器可读），供「按宠物档案筛选」使用。
    #   原先只靠 suitable 这串中文做字符串比较，文案一改筛选就崩；这里改成稳定枚举值。
    #   species: cat / dog / both    size: small / medium / large / all    stage: puppy / adult / all
    species: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # 标签列表，以 JSON 数组存储，如 ["热销", "低敏"]
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    order_items: Mapped[List["OrderItem"]] = relationship(back_populates="product")


class Order(Base):
    """订单表（一个订单包含多个 OrderItem）"""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 订单状态：pending 待付款 / paid 已付款 / shipped 已发货 / delivered 已签收
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """订单明细表"""
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)  # 下单时的单价快照

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="order_items")

    @property
    def product_name(self) -> str:
        return self.product.name if self.product else ""


class Document(Base):
    """上传文档表（RAG 知识库来源）"""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 切块数量
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="documents")


class Conversation(Base):
    """AI 对话表（一个对话包含多条消息）"""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # LangGraph 会话标识：同时作为 checkpointer thread_id 与历史查询键
    thread_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    messages: Mapped[List["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """AI 对话消息表"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), nullable=False
    )
    # 角色：user 用户 / assistant AI
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class PetProfile(Base):
    """宠物档案表：由「拍照识别」产生的结构化档案，是商品推荐的输入维度。

    与 PetSight 的 pets 表字段基本一致，另加几个为「可信度分级」服务的列：
    - species_code / size_code：物种与体型的归一值（cat·dog·other / small·medium·large·unknown），
                         供结构化筛选，避免每次都从原文重算。**注意 size_code 是"体型大小"，
                         与 body_condition（体态：偏胖/偏瘦）不是一回事。**
    - confidence_grade ：归档当时的档位快照（high/medium/low）。存快照而非现算，
                         是为了让"当时按哪一档推荐"可追溯——即便日后调整阈值，
                         已有档案的档位也不会悄悄漂移。
    - review_status    ：auto 自动通过 / pending 待人工确认 / confirmed 已确认
    """
    __tablename__ = "pet_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="我的宠物")

    # 识别结果（原文字段，保留模型给的表述）
    species: Mapped[str] = mapped_column(String(64), nullable=False, default="未知")
    breed: Mapped[str] = mapped_column(String(64), nullable=False, default="未知")
    body_condition: Mapped[str] = mapped_column(String(128), default="——")
    coat_condition: Mapped[str] = mapped_column(String(128), default="——")
    health_notes: Mapped[str] = mapped_column(Text, default="——")

    # 分级决策依据
    species_code: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    size_code: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_grade: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")

    image_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="pet_profiles")
