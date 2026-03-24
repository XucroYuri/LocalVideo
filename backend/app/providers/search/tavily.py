import httpx

from app.providers.base.search import SearchProvider, SearchResult
from app.providers.registry import search_registry


@search_registry.register("tavily")
class TavilySearchProvider(SearchProvider):
    def __init__(
        self,
        api_key: str,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://api.tavily.com"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                trust_env=False,
            )
        return self._client

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        client = await self._get_client()

        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "search_depth": "advanced",
        }

        response = await client.post("/search", json=payload)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score"),
                )
            )

        return results

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
