import json
import re
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from app.providers.base.llm import LLMProvider, LLMResponse
from app.providers.registry import llm_registry


def _normalize_anthropic_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return "https://api.anthropic.com/v1"
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if not path:
        return f"{normalized}/v1"
    return normalized


@llm_registry.register("anthropic_messages")
class AnthropicMessagesProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        model: str = "claude-sonnet-4-6",
        timeout: float = 300.0,
    ):
        self.api_key = api_key
        self.base_url = _normalize_anthropic_base_url(base_url)
        self.model = model
        self.timeout = timeout

    def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=30.0),
            trust_env=True,
        )

    def _build_payload(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int | None,
        image_url: str | None,
        image_base64: str | None,
        stream: bool,
    ) -> dict:
        user_content: list[dict] = [{"type": "text", "text": prompt}]
        if image_base64:
            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_base64,
                    },
                }
            )
        elif image_url:
            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": image_url,
                    },
                }
            )

        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
            "stream": stream,
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            image_url=image_url,
            image_base64=image_base64,
            stream=False,
        )

        async with self._create_client() as client:
            response = await client.post("/messages", json=payload)
            response.raise_for_status()
            data = response.json()

        text_parts: list[str] = []
        for item in data.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)

        return LLMResponse(
            content="\n".join(text_parts).strip(),
            model=str(data.get("model") or self.model),
            usage=data.get("usage"),
        )

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> AsyncIterator[str]:
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            image_url=image_url,
            image_base64=image_base64,
            stream=True,
        )

        async with self._create_client() as client:
            async with client.stream("POST", "/messages", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].lstrip().strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "content_block_delta":
                        continue
                    delta = event.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        yield text

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
        json_match = re.search(r"```(?:json)?\\s*([\\s\\S]*?)```", content)
        if json_match:
            content = json_match.group(1).strip()

        return json.loads(content)
