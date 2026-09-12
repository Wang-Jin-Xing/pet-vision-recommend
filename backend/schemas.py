"""Pydantic 请求 / 响应模型（接口数据契约）。"""
import re
from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import AfterValidator, BaseModel, Field

# 保守的邮箱格式校验（不引入 email-validator 依赖）
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


def _check_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value) or "." not in value.split("@")[1]:
        raise ValueError("邮箱格式不正确")
    return value


def _nonempty(max_len: int):
    """生成：去首尾空白 -> 非空 -> 限长 的校验器。"""

    def _validate(value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        if len(value) > max_len:
            raise ValueError(f"长度不能超过 {max_len} 个字符")
        return value

    return _validate


EmailStr = Annotated[str, AfterValidator(_check_email)]
UsernameStr = Annotated[str, AfterValidator(_nonempty(50))]
# 聊天消息：单条最长 2000 字，防止超长输入打爆内存与 embedding
ChatMessageStr = Annotated[str, AfterValidator(_nonempty(2000))]
# thread_id 标识
ThreadIdStr = Annotated[str, AfterValidator(_nonempty(128))]


# ============ 用户与鉴权 ============
class UserCreate(BaseModel):
    email: EmailStr
    username: UsernameStr
    # bcrypt 有效密钥长度上限为 72 字节，UTF-8 编码后不得超限
    password: str = Field(min_length=6, max_length=72, description="密码 6-72 个字符")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ============ 商品 ============
class ProductBase(BaseModel):
    name: str
    description: str = ""
    price: float = Field(ge=0)
    category: str = "其他"
    suitable: Optional[str] = None
    tags: List[str] = []
    image_url: Optional[str] = None
    stock: int = Field(default=0, ge=0)


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: int

    model_config = {"from_attributes": True}


# ============ 订单 ============
class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=999)


class OrderCreate(BaseModel):
    # 单笔订单最多 50 个条目，防止超大请求体拖垮下单事务
    items: List[OrderItemCreate] = Field(min_length=1, max_length=50)


class OrderItemOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    price: float
    quantity: int

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    status: str
    total: float
    created_at: datetime
    items: List[OrderItemOut] = []

    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    """PATCH 修改订单状态的请求体。"""
    status: str = Field(
        pattern="^(pending|paid|shipped|delivered)$",
        description="新状态：pending / paid / shipped / delivered",
    )


# ============ AI 聊天 ============
class ChatRequest(BaseModel):
    """普通问答请求体；不传 thread_id 时自动新建会话。"""
    message: ChatMessageStr
    thread_id: Optional[ThreadIdStr] = Field(
        default=None, description="会话标识（LangGraph thread_id），继续已有对话时传入"
    )


class ReviewInfo(BaseModel):
    """触发人工审核时随回答返回的审核信息（与 SSE review_required 事件一致）。"""
    review_id: str
    action: str = ""
    question: str = ""
    total: float = 0.0
    reasons: List[str] = []
    description: str = ""


class ChatReply(BaseModel):
    answer: str
    thread_id: str
    context: List[str] = []
    # True 表示图在 interrupt 处暂停：answer 为空，需调 POST /api/review 恢复
    review_required: bool = False
    review: Optional[ReviewInfo] = None


class ChatStreamRequest(BaseModel):
    """SSE 流式聊天请求体。"""
    message: ChatMessageStr
    thread_id: Optional[ThreadIdStr] = Field(
        default=None, description="传入则继续已有对话，不传则新建对话"
    )


class ReviewRequest(BaseModel):
    """人工审核请求体：用 thread_id 定位 interrupt 暂停的图执行。"""
    thread_id: ThreadIdStr
    decision: str = Field(
        pattern="^(approved|rejected)$",
        description="approved 确认 / rejected 驳回",
    )


class ReviewResult(BaseModel):
    ok: bool = True
    thread_id: str
    decision: str
    answer: str


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    """历史对话：左侧列表项，内嵌消息以便点开即看。"""
    id: int
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageOut] = []

    model_config = {"from_attributes": True}


# ============ 文档 ============
class DocumentOut(BaseModel):
    id: int
    filename: str
    created_at: datetime

    model_config = {"from_attributes": True}
