from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .project import Project


class AssetType(StrEnum):
    # Text types
    COLLECTED_INFO = "collected_info"
    CONTENT = "content"
    SUBTITLE = "subtitle"

    # Audio types
    AUDIO = "audio"

    # Image types
    REFERENCE_IMAGE = "reference_image"
    FRAME_IMAGE = "frame_image"

    # Video types
    FINAL_VIDEO = "final_video"


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    asset_type: Mapped[AssetType] = mapped_column(SQLEnum(AssetType), nullable=False)
    shot_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # File path (relative to project output_dir)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # JSON content (for storing structured data like script, collected_info)
    json_content: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Asset metadata
    asset_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationship
    project: Mapped["Project"] = relationship(back_populates="assets")
