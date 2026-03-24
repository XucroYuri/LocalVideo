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


def _normalize_openai_like_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return "https://api.openai.com/v1"
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1") or path.endswith("/v4") or path.endswith("/api/v3"):
        return normalized
    if path.startswith("/api/paas/v4"):
        return normalized
    return f"{normalized}/v1"


def _extract_error_body_preview(response: httpx.Response, *, max_length: int = 600) -> str:
    try:
        payload = response.json()
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(response.text or "").strip()
    return text[:max_length]


@llm_registry.register("openai_chat")
class OpenAIChatProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4-turbo",
        timeout: float = 300.0,
    ):
        self.api_key = api_key
        self.base_url = _normalize_openai_like_base_url(base_url)
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

    def _resolve_temperature(self, temperature: float | None) -> float | None:
        model_lower = str(self.model or "").lower()
        if "kimi-k2.5" in model_lower:
            if temperature is None or abs(float(temperature) - 1.0) > 1e-9:
                logger.info(
                    "[OpenAI Chat] Override temperature to 1.0 for model=%s (requested=%s)",
                    self.model,
                    temperature,
                )
            return 1.0
        return temperature

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

        resolved_temperature = self._resolve_temperature(temperature)
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if resolved_temperature is not None:
            payload["temperature"] = resolved_temperature
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
                    if not str(content or "").strip():
                        first_choice = (
                            data.get("choices", [{}])[0]
                            if isinstance(data.get("choices"), list) and data.get("choices")
                            else {}
                        )
                        message = (
                            first_choice.get("message") if isinstance(first_choice, dict) else {}
                        )
                        finish_reason = ""
                        message_keys: list[str] = []
                        reasoning_present = False
                        if isinstance(first_choice, dict):
                            finish_reason = str(first_choice.get("finish_reason") or "")
                        if isinstance(message, dict):
                            message_keys = sorted(message.keys())
                            reasoning_present = bool(
                                str(message.get("reasoning_content") or "").strip()
                            )
                        logger.warning(
                            "[LLM Retry] Attempt %d got empty content: model=%s base_url=%s choice_keys=%s finish_reason=%s message_keys=%s reasoning_present=%s",
                            attempt + 1,
                            self.model,
                            self.base_url,
                            sorted(first_choice.keys()) if isinstance(first_choice, dict) else [],
                            finish_reason or "unknown",
                            message_keys,
                            reasoning_present,
                        )
                        last_error = RuntimeError(
                            "LLM returned empty content"
                            f" (finish_reason={finish_reason or 'unknown'}, reasoning_present={reasoning_present})"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        raise last_error

                    result = LLMResponse(
                        content=content,
                        model=data.get("model", self.model),
                        usage=data.get("usage"),
                    )
                    return result
                except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    last_error = e
                    error_desc = str(e).strip() or repr(e)
                    logger.warning("[LLM Retry] Attempt %d failed: %s", attempt + 1, error_desc)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    raise
                except httpx.HTTPStatusError as exc:
                    body_preview = _extract_error_body_preview(exc.response)
                    logger.error(
                        "[OpenAI Chat] HTTP error status=%s model=%s base_url=%s body=%s",
                        exc.response.status_code,
                        self.model,
                        self.base_url,
                        body_preview,
                    )
                    raise

        raise last_error if last_error else RuntimeError("OpenAI chat request failed")

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

        resolved_temperature = self._resolve_temperature(temperature)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if resolved_temperature is not None:
            payload["temperature"] = resolved_temperature
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
