from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    """Search result item"""

    title: str
    url: str
    content: str
    score: float | None = None


class SearchProvider(ABC):
    """Base class for search providers"""

    name: str = "base_search"

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search for information

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        pass
