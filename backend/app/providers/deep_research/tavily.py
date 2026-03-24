import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.providers.base.deep_research import (
    DeepResearchEvent,
    DeepResearchProvider,
    DeepResearchRateLimitError,
    DeepResearchResult,
    DeepResearchSource,
    DeepResearchTask,
)
from app.providers.registry import deep_research_registry


@deep_research_registry.register("tavily")
class TavilyDeepResearchProvider(DeepResearchProvider):
    def __init__(
        self,
        api_key: str,
        timeout: float = 600.0,
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
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    @staticmethod
    def _build_payload(
        input_text: str,
        model: str = "auto",
        citation_format: str = "numbered",
        output_schema: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input": input_text,
            "model": model,
            "citation_format": citation_format,
        }
        if output_schema:
            payload["output_schema"] = output_schema
        if stream:
            payload["stream"] = True
        return payload

    @staticmethod
    def _parse_task(data: dict[str, Any]) -> DeepResearchTask:
        request_id = str(data.get("request_id") or data.get("requestId") or data.get("id") or "")
        status = str(data.get("status") or "pending")
        return DeepResearchTask(
            request_id=request_id,
            status=status,
            created_at=data.get("created_at") or data.get("createdAt"),
            input_text=data.get("input") or data.get("query"),
            model=data.get("model"),
            response_time=data.get("response_time") or data.get("responseTime"),
        )

    @staticmethod
    def _raise_for_status_with_detail(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("detail") or payload.get("error") or payload)
                else:
                    detail = str(payload)
            except Exception:
                detail = response.text[:1000]
            retry_after: float | None = None
            retry_after_raw = response.headers.get("Retry-After")
            if retry_after_raw:
                try:
                    retry_after = max(0.0, float(retry_after_raw))
                except (TypeError, ValueError):
                    retry_after = None
            if response.status_code == 429:
                message = f"{e}. Tavily response detail: {detail}" if detail else str(e)
                raise DeepResearchRateLimitError(message, retry_after=retry_after) from e
            if detail:
                raise RuntimeError(f"{e}. Tavily response detail: {detail}") from e
            raise

    @staticmethod
    def _parse_sources(raw_sources: Any) -> list[DeepResearchSource]:
        if not isinstance(raw_sources, list):
            return []
        sources: list[DeepResearchSource] = []
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            sources.append(
                DeepResearchSource(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    favicon=item.get("favicon"),
                )
            )
        return sources

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> str | dict[str, Any] | list[Any] | None:
        for key in ("content", "output", "result", "response", "answer"):
            value = data.get(key)
            if value:
                return value
        return None

    @classmethod
    def _parse_result(cls, data: dict[str, Any]) -> DeepResearchResult:
        request_id = str(data.get("request_id") or data.get("requestId") or data.get("id") or "")
        raw_status = (
            data.get("status")
            or data.get("state")
            or data.get("task_status")
            or data.get("phase")
            or ""
        )
        status = str(raw_status).strip().lower()
        content = cls._extract_content(data)
        error = data.get("error") or data.get("detail") or data.get("message")
        if not status:
            if error:
                status = "error"
            elif content is not None:
                status = "completed"
            else:
                status = "unknown"
        return DeepResearchResult(
            request_id=request_id,
            status=status,
            content=content,
            sources=cls._parse_sources(data.get("sources")),
            created_at=data.get("created_at") or data.get("createdAt"),
            completed_at=data.get("completed_at") or data.get("completedAt"),
            model=data.get("model"),
            response_time=data.get("response_time") or data.get("responseTime"),
            error=str(error) if error is not None else None,
        )

    @staticmethod
    def _extract_stream_content(payload: dict[str, Any]) -> str | None:
        # Tavily may stream plain chunks, structured objects, or openai-compatible delta objects.
        content = payload.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, dict | list):
            return json.dumps(content, ensure_ascii=False)

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, dict):
                        return json.dumps(content, ensure_ascii=False)
                    if isinstance(content, list):
                        chunks: list[str] = []
                        for part in content:
                            if isinstance(part, dict):
                                text = part.get("text")
                                if isinstance(text, str):
                                    chunks.append(text)
                            elif isinstance(part, str):
                                chunks.append(part)
                        if chunks:
                            return "".join(chunks)
        return None

    @staticmethod
    def _extract_stream_sources(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        sources = payload.get("sources")
        if isinstance(sources, list):
            return [s for s in sources if isinstance(s, dict)]

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    delta_sources = delta.get("sources")
                    if isinstance(delta_sources, list):
                        return [s for s in delta_sources if isinstance(s, dict)]
                    tool_calls = delta.get("tool_calls")
                    if isinstance(tool_calls, dict):
                        tool_response = tool_calls.get("tool_response")
                        if isinstance(tool_response, list):
                            collected: list[dict[str, Any]] = []
                            for item in tool_response:
                                if not isinstance(item, dict):
                                    continue
                                item_sources = item.get("sources")
                                if isinstance(item_sources, list):
                                    collected.extend(
                                        source
                                        for source in item_sources
                                        if isinstance(source, dict)
                                    )
                            if collected:
                                return collected
        return None

    @staticmethod
    def _extract_stream_tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
        direct_calls = payload.get("tool_calls")
        if isinstance(direct_calls, list):
            return [c for c in direct_calls if isinstance(c, dict)]
        if isinstance(direct_calls, dict):
            call_type = str(direct_calls.get("type") or "")
            if call_type == "tool_response":
                calls = direct_calls.get("tool_response")
            else:
                calls = direct_calls.get("tool_call")
            if isinstance(calls, list):
                normalized: list[dict[str, Any]] = []
                for item in calls:
                    if isinstance(item, dict):
                        payload_item = dict(item)
                        payload_item["_tool_call_type"] = call_type
                        normalized.append(payload_item)
                return normalized

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    delta_calls = delta.get("tool_calls")
                    if isinstance(delta_calls, list):
                        return [c for c in delta_calls if isinstance(c, dict)]
                    if isinstance(delta_calls, dict):
                        call_type = str(delta_calls.get("type") or "")
                        if call_type == "tool_response":
                            calls = delta_calls.get("tool_response")
                        else:
                            calls = delta_calls.get("tool_call")
                        if isinstance(calls, list):
                            normalized: list[dict[str, Any]] = []
                            for item in calls:
                                if isinstance(item, dict):
                                    payload_item = dict(item)
                                    payload_item["_tool_call_type"] = call_type
                                    normalized.append(payload_item)
                            return normalized
        return []

    @staticmethod
    def _phase_from_tool_name(tool_name: str) -> str | None:
        name = tool_name.strip().lower()
        if not name:
            return None
        if "plan" in name:
            return "planning"
        if "search" in name or "subtopic" in name or "crawl" in name:
            return "searching"
        if "generate" in name or "synth" in name or "write" in name:
            return "generating"
        if "final" in name:
            return "finalizing"
        return None

    @staticmethod
    def _phase_from_event_name(event_name: str | None) -> str | None:
        if not event_name:
            return None
        name = event_name.strip().lower()
        if any(token in name for token in ("plan", "planning")):
            return "planning"
        if any(token in name for token in ("search", "crawl", "retriev", "subtopic")):
            return "searching"
        if any(token in name for token in ("generate", "write", "synth")):
            return "generating"
        if any(token in name for token in ("final", "done", "complete")):
            return "finalizing"
        return None

    @classmethod
    def _build_phase_event(
        cls,
        current_event: str,
        payload_obj: dict[str, Any],
    ) -> DeepResearchEvent | None:
        tool_calls = cls._extract_stream_tool_calls(payload_obj)
        if tool_calls:
            first_call = tool_calls[0]
            function_obj = first_call.get("function")
            tool_name = ""
            arguments: Any = None
            if isinstance(function_obj, dict):
                tool_name = str(function_obj.get("name") or "")
                arguments = function_obj.get("arguments")
            if not tool_name:
                tool_name = str(first_call.get("name") or "")
            if arguments is None:
                arguments = first_call.get("arguments")

            sources = first_call.get("sources")
            has_sources = isinstance(sources, list) and len(sources) > 0
            call_type = str(first_call.get("_tool_call_type") or "").strip().lower()
            if call_type in {"tool_response", "response"}:
                tool_event = "response"
            elif call_type in {"tool_call", "call"}:
                tool_event = "call"
            else:
                tool_event = (
                    "response" if has_sources or first_call.get("parent_tool_call_id") else "call"
                )

            phase = cls._phase_from_tool_name(tool_name) or cls._phase_from_event_name(
                current_event
            )
            if phase:
                message_map = {
                    ("planning", "call"): "正在规划研究步骤...",
                    ("planning", "response"): "研究规划已完成，准备检索...",
                    ("searching", "call"): "正在检索相关信息...",
                    ("searching", "response"): "检索到新信息，继续扩展研究...",
                    ("generating", "call"): "正在整合材料并生成报告...",
                    ("generating", "response"): "报告内容正在生成中...",
                    ("finalizing", "call"): "正在整理最终结论...",
                    ("finalizing", "response"): "正在收尾并准备返回结果...",
                }
                message = message_map.get((phase, tool_event), f"正在执行 {phase} 阶段...")
                return DeepResearchEvent(
                    event_type="phase",
                    message=message,
                    data={
                        "phase": phase,
                        "tool_name": tool_name,
                        "tool_event": tool_event,
                        "arguments": arguments,
                        "queries": first_call.get("queries"),
                        "sources": sources if isinstance(sources, list) else None,
                        "raw_event": current_event,
                    },
                )

        phase = cls._phase_from_event_name(current_event)
        if phase:
            return DeepResearchEvent(
                event_type="phase",
                message=f"正在执行 {phase} 阶段...",
                data={"phase": phase, "raw_event": current_event},
            )

        return None

    async def create(
        self,
        input_text: str,
        model: str = "auto",
        citation_format: str = "numbered",
        output_schema: dict[str, Any] | None = None,
    ) -> DeepResearchTask:
        client = await self._get_client()
        payload = self._build_payload(
            input_text=input_text,
            model=model,
            citation_format=citation_format,
            output_schema=output_schema,
        )
        payload["api_key"] = self.api_key
        response = await client.post("/research", json=payload)
        self._raise_for_status_with_detail(response)
        return self._parse_task(response.json())

    async def get(self, request_id: str) -> DeepResearchResult:
        client = await self._get_client()
        response = await client.get(f"/research/{request_id}")
        self._raise_for_status_with_detail(response)
        return self._parse_result(response.json())

    async def stream(
        self,
        input_text: str,
        model: str = "auto",
        citation_format: str = "numbered",
        output_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[DeepResearchEvent]:
        client = await self._get_client()
        payload = self._build_payload(
            input_text=input_text,
            model=model,
            citation_format=citation_format,
            output_schema=output_schema,
            stream=True,
        )
        payload["api_key"] = self.api_key

        async with client.stream(
            "POST",
            "/research",
            json=payload,
            headers={"Accept": "text/event-stream"},
        ) as response:
            self._raise_for_status_with_detail(response)

            event_name: str | None = None
            data_lines: list[str] = []

            async def emit_event() -> DeepResearchEvent | None:
                nonlocal event_name, data_lines
                if not event_name and not data_lines:
                    return None

                raw_payload = "\n".join(data_lines).strip()
                current_event = event_name or "message"
                event_name = None
                data_lines = []

                if not raw_payload:
                    return DeepResearchEvent(event_type=current_event)

                if raw_payload == "[DONE]":
                    return DeepResearchEvent(event_type="done")

                try:
                    payload_obj = json.loads(raw_payload)
                except json.JSONDecodeError:
                    return DeepResearchEvent(
                        event_type=current_event,
                        message=raw_payload,
                    )

                request_id = (
                    payload_obj.get("request_id")
                    or payload_obj.get("requestId")
                    or payload_obj.get("id")
                )
                status = payload_obj.get("status")
                if request_id and status:
                    return DeepResearchEvent(
                        event_type="task",
                        data={
                            "request_id": str(request_id),
                            "status": str(status),
                        },
                    )

                phase_event = self._build_phase_event(current_event, payload_obj)
                if phase_event:
                    return phase_event

                content_chunk = self._extract_stream_content(payload_obj)
                if not content_chunk:
                    extracted = self._extract_content(payload_obj)
                    if isinstance(extracted, str):
                        content_chunk = extracted
                    elif extracted is not None:
                        content_chunk = json.dumps(extracted, ensure_ascii=False)

                if content_chunk:
                    return DeepResearchEvent(
                        event_type="content",
                        data={"content": content_chunk},
                    )

                sources = self._extract_stream_sources(payload_obj)
                if sources is not None:
                    return DeepResearchEvent(
                        event_type="sources",
                        data={"sources": sources},
                    )

                error = payload_obj.get("error")
                if error:
                    return DeepResearchEvent(
                        event_type="error",
                        message=str(error),
                        data={"error": error},
                    )

                return DeepResearchEvent(
                    event_type=current_event,
                    data=payload_obj,
                )

            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    continue
                if line == "":
                    event = await emit_event()
                    if event:
                        yield event

            tail_event = await emit_event()
            if tail_event:
                yield tail_event

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
