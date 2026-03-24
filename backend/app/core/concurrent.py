"""Concurrent task execution utilities."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class TaskItem(Generic[T]):
    """Single task item."""

    index: int
    data: T
    skip: bool = False  # Whether to skip (already generated)


@dataclass
class TaskResult(Generic[T]):
    """Task execution result."""

    index: int
    success: bool
    data: T | None = None
    error: str | None = None


@dataclass
class ConcurrentProgress:
    """Progress tracking for concurrent tasks."""

    total: int
    to_generate: int
    completed: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def progress_percent(self) -> int:
        """Calculate progress percentage (0-99 range for stage execution)."""
        if self.to_generate == 0:
            return 99
        return int((self.completed / self.to_generate) * 99)


async def run_concurrent_tasks(
    items: list[TaskItem[T]],
    task_fn: Callable[[TaskItem[T]], Awaitable[TaskResult[T]]],
    max_concurrency: int = 4,
    on_complete: Callable[[TaskResult[T], ConcurrentProgress], Awaitable[None]] | None = None,
    stop_on_error: bool = False,
) -> tuple[list[TaskResult[T]], ConcurrentProgress]:
    """
    Execute tasks concurrently with a semaphore to control concurrency.

    Args:
        items: List of task items
        task_fn: Async function to execute for each task
        max_concurrency: Maximum number of concurrent tasks
        on_complete: Optional callback when a single task completes (for real-time progress updates)

    Returns:
        Tuple of (list of results in original order, progress info)
    """
    semaphore = asyncio.Semaphore(max_concurrency)
    results: dict[int, TaskResult[T]] = {}

    # Calculate what needs to be generated
    to_generate_items = [item for item in items if not item.skip]
    progress = ConcurrentProgress(
        total=len(items),
        to_generate=len(to_generate_items),
        skipped=len(items) - len(to_generate_items),
    )

    logger.info(
        "[Concurrent] Starting %d tasks (to_generate=%d, skipped=%d, max_concurrency=%d)",
        len(items),
        progress.to_generate,
        progress.skipped,
        max_concurrency,
    )

    async def run_with_semaphore(item: TaskItem[T]) -> TaskResult[T]:
        if item.skip:
            # Return existing data for skipped items
            result = TaskResult(index=item.index, success=True, data=item.data)
            logger.debug("[Concurrent] Skipped item %d (already generated)", item.index)
        else:
            async with semaphore:
                logger.debug("[Concurrent] Starting item %d", item.index)
                try:
                    result = await task_fn(item)
                except Exception as e:
                    logger.error("[Concurrent] Item %d failed: %s", item.index, str(e))
                    result = TaskResult(index=item.index, success=False, error=str(e))
                logger.debug(
                    "[Concurrent] Completed item %d (success=%s)", item.index, result.success
                )

        results[item.index] = result

        # Update progress for non-skipped items
        if not item.skip:
            if result.success:
                progress.completed += 1
            else:
                progress.failed += 1

            if on_complete:
                await on_complete(result, progress)

        return result

    if stop_on_error and max_concurrency <= 1:
        stopped = False
        for item in items:
            result = await run_with_semaphore(item)
            if not item.skip and not result.success:
                stopped = True
                break
        if stopped:
            remaining = max(0, len(items) - len(results))
            logger.info(
                "[Concurrent] Stop-on-error enabled, halted remaining=%d",
                remaining,
            )
    else:
        # Execute all tasks concurrently
        await asyncio.gather(*[run_with_semaphore(item) for item in items], return_exceptions=True)

    logger.info(
        "[Concurrent] Finished: completed=%d, failed=%d, skipped=%d",
        progress.completed,
        progress.failed,
        progress.skipped,
    )

    # Return executed results in original order.
    ordered_results = [results[item.index] for item in items if item.index in results]
    return ordered_results, progress
