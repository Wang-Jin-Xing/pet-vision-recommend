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
# 宠物照片以 data URL 随消息提交时的长度上限（约 8 MB 图片）
ImageDataUrl = Annotated[str, Field(max_length=11_000_000)]


class ChatRequest(BaseModel):
    """普通问答请求体；不传 thread_id 时自动新建会话。"""
    message: ChatMessageStr
    thread_id: Optional[ThreadIdStr] = Field(
        default=None, description="会话标识（LangGraph thread_id），继续已有对话时传入"
    )
    image_data_url: Optional[ImageDataUrl] = Field(
        default=None, description="随消息上传的宠物照片（data URL），带上会先做视觉识别"
    )
    pet_profile_id: Optional[int] = Field(
        default=None, ge=1, description="选用的宠物档案 ID，推荐将按该档案条件筛选"
    )


class ReviewInfo(BaseModel):
    """触发人工审核时随回答返回的审核信息（与 SSE review_required 事件一致）。"""
    review_id: str
    action: str = ""
    question: str = ""
    total: float = 0.0
    reasons: List[str] = []
    description: str = ""
    # 因识别问题触发审核时，把识别结果与档位一并给审核人看
    pet_profile: Optional[dict] = None
    confidence_grade: str = ""


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
    image_data_url: Optional[ImageDataUrl] = Field(
        default=None, description="随消息上传的宠物照片（data URL），带上会先做视觉识别"
    )
    pet_profile_id: Optional[int] = Field(
        default=None, ge=1, description="选用的宠物档案 ID，推荐将按该档案条件筛选"
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


# ============ 宠物视觉识别 ============
class VisionResult(BaseModel):
    """一次照片识别的结果（**不入库**，供前端展示与用户确认）。"""
    species: str
    breed: str
    size: str = "不确定"
    size_code: str = ""
    body_condition: str = "——"
    coat_condition: str = "——"
    health_notes: str = "——"
    confidence: float = 0.0

    # 识别来源：vlm 正常 / rejected 拒识 / local_fallback 未配密钥 / vlm_error 调用失败
    mode: str = ""
    rejected: bool = False
    reject_reason: str = ""

    # 由置信度判出的档位（high / medium / low），前端据此提示"推荐能有多准"
    grade: str = ""
    grade_cn: str = ""
    # 是否允许建档：拒识结果为 False，但不阻断——用户仍可手动改后建档
    can_save: bool = True

    # 图片落盘后的路径，确认建档时原样回传，避免二次上传
    image_path: Optional[str] = None


class PetProfileCreate(BaseModel):
    """确认建档请求：把识别结果（用户可能在前端修正过）提交入库。"""
    name: str = Field(default="我的宠物", max_length=64)
    species: str = Field(min_length=1, max_length=64)
    breed: str = Field(default="未知", max_length=64)
    size: str = Field(default="不确定", max_length=32)
    body_condition: str = Field(default="——", max_length=128)
    coat_condition: str = Field(default="——", max_length=128)
    health_notes: str = Field(default="——", max_length=1000)
    confidence: float = Field(default=0.0, ge=0, le=1)
    image_path: Optional[str] = Field(default=None, max_length=512)


class PetProfileOut(BaseModel):
    id: int
    name: str
    species: str
    breed: str
    body_condition: str
    coat_condition: str
    health_notes: str
    species_code: str
    size_code: str
    confidence: float
    confidence_grade: str
    review_status: str
    image_path: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
