import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.providers.base.llm import LLMProvider, LLMResponse
from app.providers.llm._chat_common import extract_stream_delta_text
from app.providers.registry import llm_registry


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


def _extract_text_parts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_extract_text_parts(item))
        return parts
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "output_text", "content", "delta", "value"):
            if key in value:
                parts.extend(_extract_text_parts(value.get(key)))
        return parts
    return []


def _extract_response_text(payload: dict[str, Any]) -> str:
    direct_parts = _extract_text_parts(payload.get("output_text"))
    if direct_parts:
        return "".join(direct_parts).strip()

    output = payload.get("output")
    if isinstance(output, list):
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content_items = item.get("content")
            if not isinstance(content_items, list):
                continue
            for content_item in content_items:
                if not isinstance(content_item, dict):
                    continue
                text_parts.extend(_extract_text_parts(content_item.get("text")))
                text_parts.extend(_extract_text_parts(content_item.get("content")))
        content = "".join(text_parts).strip()
        if content:
            return content

    response_obj = payload.get("response")
    if isinstance(response_obj, dict):
        return _extract_response_text(response_obj)

    return ""


def _extract_stream_delta(event_name: str, payload: dict[str, Any]) -> str:
    payload_type = str(payload.get("type") or event_name or "").strip()
    payload_type_lower = payload_type.lower()

    if "output_text.delta" in payload_type_lower:
        delta_parts = _extract_text_parts(payload.get("delta"))
        if delta_parts:
            return "".join(delta_parts)
        text_parts = _extract_text_parts(payload.get("text"))
        if text_parts:
            return "".join(text_parts)

    if payload_type_lower in {"response.delta", "response.content_part.added"}:
        delta_parts = _extract_text_parts(payload.get("delta"))
        if delta_parts:
            return "".join(delta_parts)
        part_parts = _extract_text_parts(payload.get("part"))
        if part_parts:
            return "".join(part_parts)

    # Compatible fallback for OpenAI-chat style chunks.
    chat_delta = extract_stream_delta_text(payload)
    if chat_delta:
        return chat_delta

    return ""


@llm_registry.register("openai_responses")
class OpenAIResponsesProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4.1",
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

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> LLMResponse:
        input_messages: list[dict] = []
        if system_prompt:
            input_messages.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            )

        user_content: list[dict] = [{"type": "input_text", "text": prompt}]
        if image_base64:
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_base64}",
                }
            )
        elif image_url:
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": image_url,
                }
            )
        input_messages.append({"role": "user", "content": user_content})

        payload: dict = {
            "model": self.model,
            "input": input_messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        async with self._create_client() as client:
            response = await client.post("/responses", json=payload)
            response.raise_for_status()
            data = response.json()

        content = _extract_response_text(data)

        return LLMResponse(
            content=content,
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
        input_messages: list[dict[str, Any]] = []
        if system_prompt:
            input_messages.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            )

        user_content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if image_base64:
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_base64}",
                }
            )
        elif image_url:
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": image_url,
                }
            )
        input_messages.append({"role": "user", "content": user_content})

        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        streamed_any = False

        async with self._create_client() as client:
            async with client.stream("POST", "/responses", json=payload) as response:
                response.raise_for_status()
                current_event = ""
                data_lines: list[str] = []

                async def _consume_block(
                    event_name: str, lines: list[str]
                ) -> tuple[bool, str | None]:
                    if not lines:
                        return False, None

                    data_str = "\n".join(lines).strip()
                    if not data_str:
                        return False, None
                    if data_str == "[DONE]":
                        return True, None

                    try:
                        payload_obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        # Some proxies may stream plain text in delta events.
                        if "delta" in event_name.lower():
                            return False, data_str
                        return False, None

                    if not isinstance(payload_obj, dict):
                        return False, None

                    delta = _extract_stream_delta(event_name, payload_obj)
                    if delta:
                        return False, delta

                    payload_type = str(payload_obj.get("type") or event_name or "").strip().lower()
                    if not streamed_any and payload_type in {
                        "response.completed",
                        "response.output_text.done",
                    }:
                        final_text = _extract_response_text(payload_obj)
                        if final_text:
                            return False, final_text

                    if payload_type in {
                        "response.completed",
                        "response.failed",
                        "response.cancelled",
                    }:
                        return True, None
                    return False, None

                async for raw_line in response.aiter_lines():
                    line = raw_line.rstrip("\r")
                    if not line:
                        should_stop, chunk = await _consume_block(current_event, data_lines)
                        current_event = ""
                        data_lines = []
                        if chunk:
                            streamed_any = True
                            yield chunk
                        if should_stop:
                            break
                        continue

                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue

                    # Non-SSE fallback: try parse as plain JSON line.
                    try:
                        payload_obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload_obj, dict):
                        continue
                    delta = _extract_stream_delta("", payload_obj)
                    if delta:
                        streamed_any = True
                        yield delta
                        continue
                    if not streamed_any:
                        final_text = _extract_response_text(payload_obj)
                        if final_text:
                            streamed_any = True
                            yield final_text

                if data_lines:
                    should_stop, chunk = await _consume_block(current_event, data_lines)
                    if chunk:
                        yield chunk
                    if should_stop:
                        return

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
