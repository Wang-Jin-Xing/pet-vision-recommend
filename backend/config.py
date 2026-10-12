"""应用配置：统一从环境变量 / .env 文件读取。"""
import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend 的上一级）。用 __file__ 定位，保证无论从哪个目录启动都能读到
# 根目录的 .env。此前写成相对路径 ".env"，而启动脚本会先 cd 到 backend，
# 于是去读并不存在的 backend/.env —— LLM_API_KEY 永远为空，模型从未被调用。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

logger = logging.getLogger("petpals")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # 应用
    APP_NAME: str = "PetPals"

    # JWT
    SECRET_KEY: str = "petpals-dev-secret-please-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # Token 有效期 7 天

    # 数据库（默认使用项目目录下的 SQLite 文件）
    DATABASE_URL: str = "sqlite:///./petpals.db"

    # 文件上传目录与单文件大小上限（默认 2 MB）
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024

    # ChromaDB 向量库持久化目录与集合名
    CHROMA_DIR: str = "./data/chroma"
    COLLECTION_NAME: str = "petpals_docs"

    # CORS：逗号分隔的允许来源；默认仅放行本地开发前端
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"

    # ===== 大模型（兼容 OpenAI 协议的网关，如智谱 GLM / DeepSeek / 通义） =====
    # 未配置 LLM_API_KEY 时，工作流自动降级为本地确定性逻辑（关键词路由 + 模板），
    # 保证应用仍可完整运行；配置后由 LLM 负责意图分类与回答生成。
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4/"
    LLM_MODEL: str = "glm-4-flash"
    LLM_TEMPERATURE: float = 0.3
    LLM_TIMEOUT: int = 30

    # 知识种子目录：启动时把该目录下的 txt/md 自动索引进 ChromaDB。
    # Docker 中设为镜像内置的 /app/seed_docs（不受 uploads 卷覆盖），
    # 保证容器首次启动即有可用的 RAG 知识库；留空则只索引 UPLOAD_DIR。
    KNOWLEDGE_SEED_DIR: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def warn_if_insecure(self) -> None:
        """仍使用内置默认密钥时记录告警（不阻断启动）。"""
        if self.SECRET_KEY == "petpals-dev-secret-please-change-in-production":
            logger.warning(
                "SECRET_KEY 仍为内置开发默认值，请通过环境变量/.env 设置独立随机密钥"
            )


settings = Settings()
settings.warn_if_insecure()
