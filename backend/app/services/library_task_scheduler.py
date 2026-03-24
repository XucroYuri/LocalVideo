from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CardStage(StrEnum):
    PARSE = "A"
    DOWNLOAD = "B"
    TRANSCRIBE = "C"
    AUDIO_PREPARE = "P"
    AUDIO_PROOFREAD = "Q"
    AUDIO_NAME = "D"
    PROOFREAD = "R"
    TEXT_NAME = "E"
    REFERENCE_DESCRIBE = "F"
    REFERENCE_NAME = "G"


@dataclass(order=True, slots=True)
class _QueuedStageTask:
    priority: int
    sequence: int
    stage: CardStage = field(compare=False)
    label: str = field(compare=False)
    coro_factory: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future[Any] = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.monotonic)


class _UnifiedCardTaskScheduler:
    def __init__(self) -> None:
        self._pending_heap: list[_QueuedStageTask] = []
        self._global_limit = max(
            1, int(getattr(settings, "card_scheduler_max_concurrent_tasks", 6) or 6)
        )
        self._stage_limits = self._read_stage_limits()
        self._stage_inflight = {stage: 0 for stage in self._stage_limits}
        self._queue_changed = asyncio.Condition()
        self._workers: list[asyncio.Task[None]] = []
        self._sequence = itertools.count(1)
        self._started = False
        self._start_lock = asyncio.Lock()

    @staticmethod
    def _read_stage_limits() -> dict[CardStage, int]:
        return {
            CardStage.PARSE: max(
                1, int(getattr(settings, "card_scheduler_url_parse_concurrency", 4) or 4)
            ),
            CardStage.DOWNLOAD: max(
                1, int(getattr(settings, "card_scheduler_video_download_concurrency", 1) or 1)
            ),
            CardStage.TRANSCRIBE: max(
                1, int(getattr(settings, "card_scheduler_audio_transcribe_concurrency", 1) or 1)
            ),
            CardStage.AUDIO_PREPARE: max(
                1, int(getattr(settings, "card_scheduler_audio_prepare_concurrency", 1) or 1)
            ),
            CardStage.AUDIO_PROOFREAD: max(
                1, int(getattr(settings, "card_scheduler_audio_proofread_concurrency", 2) or 2)
            ),
            CardStage.AUDIO_NAME: max(
                1, int(getattr(settings, "card_scheduler_audio_name_concurrency", 2) or 2)
            ),
            CardStage.PROOFREAD: max(
                1, int(getattr(settings, "card_scheduler_text_proofread_concurrency", 2) or 2)
            ),
            CardStage.TEXT_NAME: max(
                1, int(getattr(settings, "card_scheduler_text_name_concurrency", 3) or 3)
            ),
            CardStage.REFERENCE_DESCRIBE: max(
                1,
                int(getattr(settings, "card_scheduler_reference_describe_concurrency", 2) or 2),
            ),
            CardStage.REFERENCE_NAME: max(
                1, int(getattr(settings, "card_scheduler_reference_name_concurrency", 2) or 2)
            ),
        }

    async def _refresh_limits_if_needed(self) -> None:
        latest_global_limit = max(
            1, int(getattr(settings, "card_scheduler_max_concurrent_tasks", 6) or 6)
        )
        latest_stage_limits = self._read_stage_limits()
        global_changed = latest_global_limit != self._global_limit
        stage_changed = latest_stage_limits != self._stage_limits
        if not global_changed and not stage_changed:
            return

        async with self._start_lock:
            latest_global_limit = max(
                1, int(getattr(settings, "card_scheduler_max_concurrent_tasks", 6) or 6)
            )
            latest_stage_limits = self._read_stage_limits()
            global_changed = latest_global_limit != self._global_limit
            stage_changed = latest_stage_limits != self._stage_limits
            if not global_changed and not stage_changed:
                return

            if stage_changed:
                async with self._queue_changed:
                    self._stage_limits = latest_stage_limits
                    for stage in latest_stage_limits:
                        self._stage_inflight.setdefault(stage, 0)
                    self._queue_changed.notify_all()

            if self._started and global_changed and latest_global_limit > len(self._workers):
                for worker_index in range(len(self._workers), latest_global_limit):
                    worker = asyncio.create_task(self._worker_loop(worker_index + 1))
                    self._workers.append(worker)
            if self._started:
                self._global_limit = max(self._global_limit, latest_global_limit)
            else:
                self._global_limit = latest_global_limit

            logger.info(
                "[CardScheduler] reconfigured workers=%s requested_workers=%s stage_limits=%s",
                len(self._workers),
                latest_global_limit,
                {stage.value: limit for stage, limit in self._stage_limits.items()},
            )

    async def _ensure_started(self) -> None:
        await self._refresh_limits_if_needed()
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            for worker_index in range(self._global_limit):
                worker = asyncio.create_task(self._worker_loop(worker_index + 1))
                self._workers.append(worker)
            self._started = True
            logger.info(
                "[CardScheduler] started workers=%s stage_limits=%s",
                self._global_limit,
                {stage.value: limit for stage, limit in self._stage_limits.items()},
            )

    def _pop_next_runnable_locked(self) -> _QueuedStageTask | None:
        if not self._pending_heap:
            return None
        blocked: list[_QueuedStageTask] = []
        selected: _QueuedStageTask | None = None
        while self._pending_heap:
            candidate = heapq.heappop(self._pending_heap)
            if candidate.future.done():
                continue
            limit = int(self._stage_limits.get(candidate.stage, 1))
            inflight = int(self._stage_inflight.get(candidate.stage, 0))
            if inflight < limit:
                selected = candidate
                break
            blocked.append(candidate)

        for one in blocked:
            heapq.heappush(self._pending_heap, one)
        if selected is None:
            return None

        self._stage_inflight[selected.stage] = int(self._stage_inflight.get(selected.stage, 0)) + 1
        return selected

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            async with self._queue_changed:
                while True:
                    queued_task = self._pop_next_runnable_locked()
                    if queued_task is not None:
                        break
                    await self._queue_changed.wait()
            started_at = time.monotonic()
            stage_task: asyncio.Task[Any] | None = None
            future_cancel_callback: Callable[[asyncio.Future[Any]], None] | None = None
            try:
                stage_task = asyncio.create_task(queued_task.coro_factory())

                def _cancel_stage_task_if_needed(fut: asyncio.Future[Any]) -> None:
                    if fut.cancelled() and stage_task and not stage_task.done():
                        stage_task.cancel()

                future_cancel_callback = _cancel_stage_task_if_needed
                queued_task.future.add_done_callback(future_cancel_callback)
                if queued_task.future.cancelled():
                    if not stage_task.done():
                        stage_task.cancel()
                result = await stage_task
            except asyncio.CancelledError:
                if queued_task.future.cancelled():
                    logger.info(
                        "[CardScheduler] canceled worker=%s stage=%s label=%s queue_wait=%.2fs exec=%.2fs",
                        worker_id,
                        queued_task.stage.value,
                        queued_task.label,
                        started_at - queued_task.enqueued_at,
                        time.monotonic() - started_at,
                    )
                    continue
                if not queued_task.future.done():
                    queued_task.future.cancel()
                raise
            except Exception as exc:  # noqa: BLE001
                if not queued_task.future.done():
                    queued_task.future.set_exception(exc)
                logger.warning(
                    "[CardScheduler] failed worker=%s stage=%s label=%s queue_wait=%.2fs exec=%.2fs error=%s",
                    worker_id,
                    queued_task.stage.value,
                    queued_task.label,
                    started_at - queued_task.enqueued_at,
                    time.monotonic() - started_at,
                    exc,
                )
            else:
                if not queued_task.future.done():
                    queued_task.future.set_result(result)
                logger.info(
                    "[CardScheduler] done worker=%s stage=%s label=%s queue_wait=%.2fs exec=%.2fs",
                    worker_id,
                    queued_task.stage.value,
                    queued_task.label,
                    started_at - queued_task.enqueued_at,
                    time.monotonic() - started_at,
                )
            finally:
                if future_cancel_callback is not None:
                    queued_task.future.remove_done_callback(future_cancel_callback)
                async with self._queue_changed:
                    current = int(self._stage_inflight.get(queued_task.stage, 0))
                    self._stage_inflight[queued_task.stage] = max(0, current - 1)
                    self._queue_changed.notify_all()

    async def run(
        self,
        *,
        stage: CardStage,
        label: str,
        coro_factory: Callable[[], Awaitable[T]],
        priority: int = 100,
    ) -> T:
        await self._ensure_started()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        queued_task = _QueuedStageTask(
            priority=int(priority),
            sequence=next(self._sequence),
            stage=stage,
            label=label,
            coro_factory=coro_factory,
            future=future,
        )
        async with self._queue_changed:
            heapq.heappush(self._pending_heap, queued_task)
            self._queue_changed.notify_all()
        return await future


_CARD_TASK_SCHEDULER = _UnifiedCardTaskScheduler()


async def run_card_stage(
    *,
    stage: CardStage,
    label: str,
    coro_factory: Callable[[], Awaitable[T]],
    priority: int = 100,
) -> T:
    return await _CARD_TASK_SCHEDULER.run(
        stage=stage,
        label=label,
        coro_factory=coro_factory,
        priority=priority,
    )
