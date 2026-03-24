from datetime import datetime

from pydantic import BaseModel, Field

from app.models.source import SourceType


class SourceBase(BaseModel):
    type: SourceType
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    selected: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)
    selected: bool | None = None


class SourceResponse(SourceBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    total: int


class SourceBatchUpdate(BaseModel):
    """批量更新来源的 selected 状态"""

    source_ids: list[int]
    selected: bool


class SourceImportFromTextLibraryRequest(BaseModel):
    text_library_ids: list[int]


class SourceImportFromTextLibraryResultItem(BaseModel):
    text_library_id: int
    status: str
    source_id: int | None = None
    message: str


class SourceImportFromTextLibraryResponse(BaseModel):
    success: bool
    summary: dict[str, int]
    results: list[SourceImportFromTextLibraryResultItem]
