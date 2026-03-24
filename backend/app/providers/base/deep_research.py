from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


class DeepResearchRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class DeepResearchSource:
    title: str
    url: str
    favicon: str | None = None


@dataclass
class DeepResearchTask:
    request_id: str
    status: str
    created_at: str | None = None
    input_text: str | None = None
    model: str | None = None
    response_time: float | None = None


@dataclass
class DeepResearchResult:
    request_id: str
    status: str
    content: str | dict[str, Any] | list[Any] | None = None
    sources: list[DeepResearchSource] | None = None
    created_at: str | None = None
    completed_at: str | None = None
    model: str | None = None
    response_time: float | None = None
    error: str | None = None


@dataclass
class DeepResearchEvent:
    event_type: str
    message: str | None = None
    data: dict[str, Any] | None = None


class DeepResearchProvider(ABC):
    name: str = "base_deep_research"

    @abstractmethod
    async def create(
        self,
        input_text: str,
        model: str = "auto",
        citation_format: str = "numbered",
        output_schema: dict[str, Any] | None = None,
    ) -> DeepResearchTask:
        pass

    @abstractmethod
    async def get(self, request_id: str) -> DeepResearchResult:
        pass

    @abstractmethod
    async def stream(
        self,
        input_text: str,
        model: str = "auto",
        citation_format: str = "numbered",
        output_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[DeepResearchEvent]:
        pass
