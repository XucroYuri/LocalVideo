from enum import StrEnum

from sqlalchemy import JSON, Boolean, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ProviderType(StrEnum):
    LLM = "llm"
    SEARCH = "search"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"


class ProviderConfig(Base, TimestampMixin):
    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    provider_type: Mapped[ProviderType] = mapped_column(SQLEnum(ProviderType), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)

    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Configuration parameters
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
