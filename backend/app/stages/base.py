from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import StageResult
from app.models.project import Project
from app.models.stage import StageExecution


class StageHandler(ABC):
    @abstractmethod
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        pass

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        return None


__all__ = ["StageHandler", "StageResult"]
