import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from app.providers.base.llm import LLMProvider, LLMResponse
from app.providers.llm._chat_common import (
    build_chat_messages,
    extract_chat_content,
    extract_stream_delta_text,
)
from app.providers.registry import llm_registry

logger = logging.getLogger(__name__)


def _normalize_gemini_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return "https://generativelanguage.googleapis.com/v1beta/openai"
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1beta/openai"):
        return normalized
    if path.endswith("/v1beta"):
        return f"{normalized}/openai"
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/v1beta/openai"
    return "https://generativelanguage.googleapis.com/v1beta/openai"


@llm_registry.register("gemini")
class GeminiChatProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
        model: str = "gemini-3-flash-preview",
        timeout: float = 300.0,
    ):
        self.api_key = api_key
        self.base_url = _normalize_gemini_base_url(base_url)
        self.model = model
        self.timeout = timeout

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=30.0),
            trust_env=True,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> LLMResponse:
        messages = build_chat_messages(
            prompt,
            system_prompt=system_prompt,
            image_url=image_url,
            image_base64=image_base64,
        )

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        max_retries = 3
        last_error: Exception | None = None
        for attempt in range(max_retries):
            async with self._create_client() as client:
                try:
                    response = await client.post("/chat/completions", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    content = extract_chat_content(data)
                    return LLMResponse(
                        content=content,
                        model=str(data.get("model") or self.model),
                        usage=data.get("usage"),
                    )
                except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                    last_error = exc
                    logger.warning(
                        "[Gemini Retry] Attempt %d failed: %s",
                        attempt + 1,
                        str(exc).strip() or repr(exc),
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    raise
        raise last_error if last_error else RuntimeError("Gemini request failed")

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> AsyncIterator[str]:
        messages = build_chat_messages(
            prompt,
            system_prompt=system_prompt,
            image_url=image_url,
            image_base64=image_base64,
        )

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with self._create_client() as client:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip()
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta_text = extract_stream_delta_text(data)
                    if delta_text:
                        yield delta_text

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,
    ) -> dict:
        json_system = (system_prompt or "") + "\nYou must respond with valid JSON only."
        response = await self.generate(
            prompt=prompt,
            system_prompt=json_system,
            temperature=temperature,
        )
        content = response.content.strip()
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if json_match:
            content = json_match.group(1).strip()
        return json.loads(content)

    async def close(self):
        pass
