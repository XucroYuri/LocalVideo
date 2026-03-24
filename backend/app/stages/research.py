import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.errors import StageRuntimeError
from app.llm.runtime import resolve_llm_runtime
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers import (
    DeepResearchRateLimitError,
    DeepResearchSource,
    get_deep_research_provider,
    get_search_provider,
)
from app.stages.common.log_utils import log_stage_separator

from . import register_stage
from ._generation_log import truncate_generation_text
from .base import StageHandler, StageResult
from .prompts import RESEARCH_SYSTEM, RESEARCH_USER

logger = logging.getLogger(__name__)


@register_stage(StageType.RESEARCH)
class ResearchHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        keywords = project.keywords
        if not keywords:
            return StageResult(success=False, error="No keywords provided for research")

        if not settings.search_tavily_api_key:
            return StageResult(success=False, error="Tavily API key not configured")

        search_mode = self._resolve_search_mode(input_data)

        try:
            if search_mode == "deep":
                return await self._run_deep_research(
                    db=db,
                    stage=stage,
                    keywords=keywords,
                    input_data=input_data,
                )
            return await self._run_web_search(
                db=db,
                stage=stage,
                keywords=keywords,
                input_data=input_data,
            )
        except Exception as e:
            return StageResult(success=False, error=str(e))

    async def _run_web_search(
        self,
        db: AsyncSession,
        stage: StageExecution,
        keywords: str,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        await self._persist_research_progress(
            db=db,
            stage=stage,
            keywords=keywords,
            progress=10,
            search_mode="web",
            research_status="searching",
            research_phase="searching",
            progress_message="正在检索网页信息...",
        )

        max_results = 10
        if input_data and input_data.get("max_results") is not None:
            try:
                max_results = int(input_data.get("max_results"))
            except (TypeError, ValueError):
                max_results = 10
        max_results = max(1, min(max_results, 20))

        search_provider_name = settings.default_search_provider or "tavily"
        search_provider = get_search_provider(
            search_provider_name,
            api_key=settings.search_tavily_api_key,
        )

        log_stage_separator(logger)
        logger.info("[Research] Web Search")
        logger.info("[Input] keywords: %s, max_results: %d", keywords, max_results)
        log_stage_separator(logger)

        search_results = await search_provider.search(keywords, max_results=max_results)

        logger.info("[Output] result_count: %d", len(search_results))
        logger.info("[Output] titles: %s", [r.title for r in search_results])
        log_stage_separator(logger)

        search_text = "\n\n".join(
            [f"### {r.title}\nURL: {r.url}\n{r.content}" for r in search_results]
        )

        llm_runtime = resolve_llm_runtime(input_data)
        llm_provider = llm_runtime.provider

        prompt = RESEARCH_USER.format(
            keywords=keywords,
            search_results=search_text,
        )

        log_stage_separator(logger)
        logger.info("[Research] LLM Generate - Report")
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        logger.info("[Input] prompt: %s", truncate_generation_text(prompt))
        logger.info(
            "[Input] system_prompt: %s",
            truncate_generation_text(RESEARCH_SYSTEM),
        )
        log_stage_separator(logger)

        await self._persist_research_progress(
            db=db,
            stage=stage,
            keywords=keywords,
            progress=75,
            search_mode="web",
            research_status="analyzing",
            research_phase="generating",
            progress_message="正在使用 LLM 分析搜索结果...",
        )

        use_stream = self._truthy((input_data or {}).get("llm_stream"), default=True)
        report = ""
        if use_stream:
            logger.info("[Research] LLM streaming enabled for web search report")
            stream_chunks: list[str] = []
            chunks_since_flush = 0
            chars_since_flush = 0
            try:
                async for chunk in llm_provider.generate_stream(
                    prompt=prompt,
                    system_prompt=RESEARCH_SYSTEM,
                    temperature=0.3,
                ):
                    text = str(chunk or "")
                    if not text:
                        continue
                    stream_chunks.append(text)
                    chunks_since_flush += 1
                    chars_since_flush += len(text)
                    if chunks_since_flush < 4 and chars_since_flush < 800:
                        continue

                    partial_report = "".join(stream_chunks)
                    progress_boost = min(18, len(partial_report) // 900)
                    progress = min(94, max(stage.progress, 76 + progress_boost))
                    await self._persist_research_progress(
                        db=db,
                        stage=stage,
                        keywords=keywords,
                        progress=progress,
                        search_mode="web",
                        research_status="analyzing",
                        research_phase="generating",
                        partial_report=partial_report,
                        progress_message=(
                            f"正在接收 LLM 流式输出...（已接收约 {len(partial_report)} 字）"
                        ),
                    )
                    chunks_since_flush = 0
                    chars_since_flush = 0

                report = "".join(stream_chunks).strip()
                if report:
                    await self._persist_research_progress(
                        db=db,
                        stage=stage,
                        keywords=keywords,
                        progress=max(stage.progress, 95),
                        search_mode="web",
                        research_status="analyzing",
                        research_phase="finalizing",
                        partial_report=report,
                        progress_message="LLM 流式输出完成，正在整理研究结果...",
                    )
                else:
                    logger.warning(
                        "[Research] LLM stream ended without content, fallback to non-stream generate"
                    )
            except Exception as e:
                logger.warning(
                    "[Research] LLM stream failed (%r), fallback to non-stream generate",
                    e,
                )

        if not report:
            response = await llm_provider.generate(
                prompt=prompt,
                system_prompt=RESEARCH_SYSTEM,
                temperature=0.3,
            )
            report = response.content

        logger.info("[Output] report: %s", truncate_generation_text(report))
        log_stage_separator(logger)

        raw_results = [
            {"title": r.title, "url": r.url, "content": r.content, "score": r.score}
            for r in search_results
        ]

        return StageResult(
            success=True,
            data={
                "keywords": keywords,
                "search_mode": "web",
                "report": report,
                "raw_search_results": raw_results,
            },
        )

    async def _run_deep_research(
        self,
        db: AsyncSession,
        stage: StageExecution,
        keywords: str,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        deep_provider = get_deep_research_provider(
            settings.default_search_provider or "tavily",
            api_key=settings.search_tavily_api_key,
        )

        model = str((input_data or {}).get("research_model") or "auto")
        citation_format = str((input_data or {}).get("citation_format") or "numbered")
        output_schema = (input_data or {}).get("output_schema")
        if not isinstance(output_schema, dict):
            output_schema = None
        use_stream = self._truthy((input_data or {}).get("research_stream"), default=True)
        poll_interval = self._to_float((input_data or {}).get("poll_interval_seconds"), 6.0)
        timeout_seconds = self._to_float((input_data or {}).get("poll_timeout_seconds"), 900.0)
        stream_idle_timeout_seconds = self._to_float(
            (input_data or {}).get("stream_idle_timeout_seconds"), 45.0
        )
        stream_timeout_seconds = self._to_float(
            (input_data or {}).get("stream_timeout_seconds"), 600.0
        )

        request_id: str | None = None
        streamed_report = ""
        streamed_sources: list[dict[str, Any]] = []

        await self._persist_research_progress(
            db=db,
            stage=stage,
            keywords=keywords,
            progress=5,
            search_mode="deep",
            research_status="starting",
            progress_message="已启动 Deep Research，等待任务响应...",
        )

        if use_stream:
            try:
                content_chunks: list[str] = []
                stream_iter = deep_provider.stream(
                    input_text=keywords,
                    model=model,
                    citation_format=citation_format,
                    output_schema=output_schema,
                ).__aiter__()
                stream_start = asyncio.get_running_loop().time()
                while True:
                    elapsed = asyncio.get_running_loop().time() - stream_start
                    if elapsed > stream_timeout_seconds:
                        raise StageRuntimeError(
                            f"Deep research stream timeout after {int(stream_timeout_seconds)}s"
                        )
                    timeout = max(
                        1.0, min(stream_idle_timeout_seconds, stream_timeout_seconds - elapsed)
                    )
                    try:
                        event = await asyncio.wait_for(stream_iter.__anext__(), timeout=timeout)
                    except StopAsyncIteration:
                        break

                    if event.event_type == "task":
                        if event.data:
                            request_id = str(event.data.get("request_id") or request_id or "")
                            status_value = str(event.data.get("status") or "running")
                            phase = self._normalize_phase(status_value)
                            phase_progress = self._phase_progress(phase)
                            phase_message = self._phase_message(phase)
                            await self._persist_research_progress(
                                db=db,
                                stage=stage,
                                keywords=keywords,
                                progress=phase_progress,
                                search_mode="deep",
                                research_status=status_value,
                                research_phase=phase,
                                request_id=request_id or None,
                                progress_message=phase_message,
                            )
                        continue

                    if event.event_type == "phase":
                        phase = self._normalize_phase((event.data or {}).get("phase"))
                        phase_progress = self._phase_progress(phase)
                        phase_message = event.message or self._phase_message(phase)
                        phase_sources = self._normalize_deep_sources(
                            (event.data or {}).get("sources")
                        )
                        if phase_sources:
                            streamed_sources = phase_sources
                        await self._persist_research_progress(
                            db=db,
                            stage=stage,
                            keywords=keywords,
                            progress=max(stage.progress, phase_progress),
                            search_mode="deep",
                            research_status=phase,
                            research_phase=phase,
                            request_id=request_id,
                            sources=phase_sources or None,
                            progress_message=phase_message,
                        )
                        continue

                    if event.event_type == "content":
                        content = (event.data or {}).get("content")
                        if isinstance(content, str) and content:
                            content_chunks.append(content)
                            if len(content_chunks) % 3 == 0:
                                progress = min(
                                    92, max(stage.progress, 75 + len(content_chunks) // 3)
                                )
                                await self._persist_research_progress(
                                    db=db,
                                    stage=stage,
                                    keywords=keywords,
                                    progress=progress,
                                    search_mode="deep",
                                    research_status="running",
                                    research_phase="generating",
                                    request_id=request_id,
                                    partial_report="".join(content_chunks)[-5000:],
                                    progress_message="正在生成研究报告...",
                                )
                        continue

                    if event.event_type == "sources":
                        raw_sources = (event.data or {}).get("sources")
                        streamed_sources = self._normalize_deep_sources(raw_sources)
                        await self._persist_research_progress(
                            db=db,
                            stage=stage,
                            keywords=keywords,
                            progress=max(stage.progress, 90),
                            search_mode="deep",
                            research_status="running",
                            research_phase="finalizing",
                            request_id=request_id,
                            sources=streamed_sources,
                            progress_message="正在整理引用来源...",
                        )
                        continue

                    if event.event_type == "error":
                        raise StageRuntimeError(event.message or "Deep research stream failed")

                    if event.event_type == "done":
                        await self._persist_research_progress(
                            db=db,
                            stage=stage,
                            keywords=keywords,
                            progress=max(stage.progress, 95),
                            search_mode="deep",
                            research_status="done",
                            research_phase="finalizing",
                            request_id=request_id,
                            progress_message="研究已完成，正在整理结果...",
                        )
                        break

                streamed_report = "".join(content_chunks).strip()
            except Exception as e:
                logger.warning("[Research][Deep] stream failed, fallback to polling: %r", e)

        if streamed_report:
            raw_results = self._build_raw_results_from_sources(streamed_sources)
            return StageResult(
                success=True,
                data={
                    "keywords": keywords,
                    "search_mode": "deep",
                    "request_id": request_id,
                    "model": model,
                    "report": streamed_report,
                    "sources": streamed_sources,
                    "raw_search_results": raw_results,
                },
            )
        initial_status = "pending"
        if request_id:
            initial_status = "running"
            await self._persist_research_progress(
                db=db,
                stage=stage,
                keywords=keywords,
                progress=max(stage.progress, 20),
                search_mode="deep",
                research_status=initial_status,
                research_phase="running",
                request_id=request_id,
                progress_message="任务已创建，等待 Tavily 返回结果...",
            )
        else:
            task = await deep_provider.create(
                input_text=keywords,
                model=model,
                citation_format=citation_format,
                output_schema=output_schema,
            )
            request_id = task.request_id
            initial_status = task.status

            if not request_id:
                return StageResult(
                    success=False,
                    error=(
                        "Deep research request accepted but no request_id returned. "
                        "Try setting research_stream=true to inspect raw stream behavior."
                    ),
                )

            await self._persist_research_progress(
                db=db,
                stage=stage,
                keywords=keywords,
                progress=max(stage.progress, 20),
                search_mode="deep",
                research_status=initial_status,
                research_phase=self._normalize_phase(initial_status),
                request_id=request_id,
                progress_message=self._phase_message(self._normalize_phase(initial_status)),
            )

        start = asyncio.get_running_loop().time()
        rate_limit_backoff = max(6.0, poll_interval)
        last_status = initial_status.lower() if initial_status else ""
        last_status_change_at = start
        last_status_log_minute = -1

        while True:
            try:
                result = await deep_provider.get(request_id)
                rate_limit_backoff = max(6.0, poll_interval)
            except DeepResearchRateLimitError as e:
                elapsed = asyncio.get_running_loop().time() - start
                if elapsed > timeout_seconds:
                    return StageResult(
                        success=False,
                        error=(
                            f"Deep research timed out after {int(timeout_seconds)} seconds"
                            f" while waiting for Tavily rate limit recovery (request_id={request_id})"
                        ),
                    )

                wait_seconds = e.retry_after if e.retry_after is not None else rate_limit_backoff
                wait_seconds = max(3.0, min(wait_seconds, 60.0))
                rate_limit_backoff = min(60.0, wait_seconds * 1.6)

                await self._persist_research_progress(
                    db=db,
                    stage=stage,
                    keywords=keywords,
                    progress=max(stage.progress, 30),
                    search_mode="deep",
                    research_status="rate_limited",
                    research_phase="searching",
                    request_id=request_id,
                    progress_message=(
                        f"Deep Research 触发 Tavily 限流，{int(wait_seconds)} 秒后自动重试..."
                    ),
                )
                await asyncio.sleep(wait_seconds)
                continue

            status = (result.status or "").lower()
            if not status:
                status = "unknown"
            now = asyncio.get_running_loop().time()
            if status != last_status:
                last_status = status
                last_status_change_at = now
                logger.info(
                    "[Research][Deep] poll status changed: request_id=%s status=%s",
                    request_id,
                    status,
                )
            phase = self._normalize_phase(status)
            mapped_progress = self._phase_progress(phase)
            mapped_message = self._phase_message(phase)
            elapsed = now - start
            if status in {"unknown"}:
                return StageResult(
                    success=False,
                    error=(
                        "Deep research get 返回缺少可识别状态，"
                        f"request_id={request_id}, detail={result.error or 'empty response'}"
                    ),
                )
            if (
                status in {"pending", "queued", "running", "processing", "in_progress"}
                and elapsed >= 60
            ):
                waited_minutes = max(1, int(elapsed // 60))
                if waited_minutes != last_status_log_minute:
                    last_status_log_minute = waited_minutes
                    logger.info(
                        "[Research][Deep] still waiting: request_id=%s status=%s elapsed=%sm",
                        request_id,
                        status,
                        waited_minutes,
                    )
                mapped_message = (
                    f"{mapped_message}（Tavily 状态: {status}，已等待 {waited_minutes} 分钟）"
                )

            if result.error and status not in {"completed", "success", "done"}:
                return StageResult(
                    success=False,
                    error=result.error,
                )

            if status in {"completed", "success", "done"}:
                report = self._normalize_deep_report(result.content)
                if not report:
                    return StageResult(
                        success=False,
                        error="Deep research completed but empty report was returned",
                    )
                normalized_sources = self._normalize_deep_sources(result.sources)
                raw_results = self._build_raw_results_from_sources(normalized_sources)
                await self._persist_research_progress(
                    db=db,
                    stage=stage,
                    keywords=keywords,
                    progress=95,
                    search_mode="deep",
                    research_status=status,
                    research_phase="finalizing",
                    request_id=request_id,
                    sources=normalized_sources,
                    progress_message="研究完成，正在返回结果...",
                )
                return StageResult(
                    success=True,
                    data={
                        "keywords": keywords,
                        "search_mode": "deep",
                        "request_id": request_id,
                        "model": result.model or model,
                        "status": status,
                        "report": report,
                        "sources": normalized_sources,
                        "raw_search_results": raw_results,
                    },
                )

            if status in {"failed", "error", "cancelled", "canceled"}:
                return StageResult(
                    success=False,
                    error=result.error or f"Deep research failed with status: {result.status}",
                )

            if elapsed > timeout_seconds:
                return StageResult(
                    success=False,
                    error=(
                        f"Deep research timed out after {int(timeout_seconds)} seconds"
                        f" (request_id={request_id})"
                    ),
                )

            stalled_seconds = now - last_status_change_at
            progress = max(stage.progress, mapped_progress)
            if stalled_seconds >= 120 and progress < 85:
                progress = min(85, progress + 1)
            await self._persist_research_progress(
                db=db,
                stage=stage,
                keywords=keywords,
                progress=progress,
                search_mode="deep",
                research_status=status or "running",
                research_phase=phase,
                request_id=request_id,
                progress_message=mapped_message,
            )
            await asyncio.sleep(max(0.5, poll_interval))

    @staticmethod
    def _resolve_search_mode(input_data: dict[str, Any] | None) -> str:
        mode = str((input_data or {}).get("search_mode") or "web").strip().lower()
        if mode in {"deep", "deep_research"}:
            return "deep"
        return "web"

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _truthy(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @classmethod
    def _normalize_deep_report(cls, content: str | dict[str, Any] | list[Any] | None) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, dict):
            for key in ("content", "report", "answer", "result", "output"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            if all(isinstance(item, str) for item in content):
                return "\n".join(item.strip() for item in content if item.strip())
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    @classmethod
    def _normalize_deep_sources(
        cls,
        sources: list[DeepResearchSource] | list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not sources:
            return []
        normalized: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in sources:
            if isinstance(item, DeepResearchSource):
                title = item.title
                url = item.url
                favicon = item.favicon
            elif isinstance(item, dict):
                title = str(item.get("title") or "")
                url = str(item.get("url") or "")
                favicon = item.get("favicon")
            else:
                continue

            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            normalized.append(
                {
                    "title": title,
                    "url": url,
                    "favicon": favicon,
                }
            )
        return normalized

    @staticmethod
    def _build_raw_results_from_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raw_results: list[dict[str, Any]] = []
        for source in sources:
            raw_results.append(
                {
                    "title": source.get("title", ""),
                    "url": source.get("url", ""),
                    "content": "",
                    "score": None,
                }
            )
        return raw_results

    @staticmethod
    async def _persist_research_progress(
        db: AsyncSession,
        stage: StageExecution,
        keywords: str,
        progress: int,
        search_mode: str,
        research_status: str,
        research_phase: str | None = None,
        request_id: str | None = None,
        partial_report: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        progress_message: str | None = None,
    ) -> None:
        stage.progress = max(0, min(99, progress))
        output_data = dict(stage.output_data or {})
        output_data["keywords"] = keywords
        output_data["search_mode"] = search_mode
        output_data["research_status"] = research_status
        if research_phase:
            output_data["research_phase"] = research_phase
        if request_id:
            output_data["request_id"] = request_id
        if partial_report is not None:
            output_data["partial_report"] = partial_report
        if sources is not None:
            output_data["sources"] = sources
        if progress_message:
            output_data["progress_message"] = progress_message
        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    @staticmethod
    def _normalize_phase(value: Any) -> str:
        text = str(value or "").strip().lower()
        if any(token in text for token in ("plan", "planning")):
            return "planning"
        if text in {"pending", "queued"}:
            return "planning"
        if any(token in text for token in ("search", "crawl", "retriev", "subtopic")):
            return "searching"
        if any(token in text for token in ("generate", "write", "synth")):
            return "generating"
        if any(token in text for token in ("final", "complete", "done")):
            return "finalizing"
        if text in {"running", "processing"} or "in_progress" in text:
            return "searching"
        return "running"

    @staticmethod
    def _phase_progress(phase: str) -> int:
        mapping = {
            "planning": 15,
            "searching": 40,
            "generating": 75,
            "finalizing": 92,
            "running": 25,
        }
        return mapping.get(phase, 25)

    @staticmethod
    def _phase_message(phase: str) -> str:
        mapping = {
            "planning": "正在规划研究步骤...",
            "searching": "正在检索并整理关键信息...",
            "generating": "正在整合材料并生成研究报告...",
            "finalizing": "正在整理引用来源并收尾...",
            "running": "Deep Research 执行中...",
        }
        return mapping.get(phase, "Deep Research 执行中...")

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        if not project.keywords:
            return "Project must have keywords for research stage"
        return None
