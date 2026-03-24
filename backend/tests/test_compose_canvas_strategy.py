from pathlib import Path

import pytest

from app.core.errors import StageValidationError
from app.stages.compose import (
    COMPOSE_CANVAS_STRATEGY_FIRST_SHOT,
    COMPOSE_CANVAS_STRATEGY_FIXED,
    COMPOSE_CANVAS_STRATEGY_MAX_SIZE,
    COMPOSE_CANVAS_STRATEGY_MOST_COMMON,
    ComposeHandler,
)


@pytest.mark.asyncio
async def test_resolve_concat_canvas_uses_max_size(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = ComposeHandler()
    video_files = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4")]
    dimensions = {
        "a.mp4": (720, 1280),
        "b.mp4": (1080, 1920),
        "c.mp4": (960, 540),
    }

    async def _probe(media_path: Path) -> tuple[int, int] | None:
        return dimensions.get(media_path.name)

    monkeypatch.setattr(handler, "_probe_video_dimensions", _probe)

    result = await handler._resolve_concat_canvas(
        video_files,
        canvas_strategy=COMPOSE_CANVAS_STRATEGY_MAX_SIZE,
    )

    assert result == (1080, 1920)


@pytest.mark.asyncio
async def test_resolve_concat_canvas_uses_most_common(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = ComposeHandler()
    video_files = [Path("a.mp4"), Path("b.mp4"), Path("c.mp4"), Path("d.mp4")]
    dimensions = {
        "a.mp4": (720, 1280),
        "b.mp4": (720, 1280),
        "c.mp4": (1080, 1920),
        "d.mp4": (960, 540),
    }

    async def _probe(media_path: Path) -> tuple[int, int] | None:
        return dimensions.get(media_path.name)

    monkeypatch.setattr(handler, "_probe_video_dimensions", _probe)

    result = await handler._resolve_concat_canvas(
        video_files,
        canvas_strategy=COMPOSE_CANVAS_STRATEGY_MOST_COMMON,
    )

    assert result == (720, 1280)


@pytest.mark.asyncio
async def test_resolve_concat_canvas_uses_first_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = ComposeHandler()
    video_files = [Path("a.mp4"), Path("b.mp4")]
    dimensions = {
        "a.mp4": (721, 1281),
        "b.mp4": (1080, 1920),
    }

    async def _probe(media_path: Path) -> tuple[int, int] | None:
        return dimensions.get(media_path.name)

    monkeypatch.setattr(handler, "_probe_video_dimensions", _probe)

    result = await handler._resolve_concat_canvas(
        video_files,
        canvas_strategy=COMPOSE_CANVAS_STRATEGY_FIRST_SHOT,
    )

    assert result == (720, 1280)


@pytest.mark.asyncio
async def test_resolve_concat_canvas_uses_fixed_resolution() -> None:
    handler = ComposeHandler()

    result = await handler._resolve_concat_canvas(
        [Path("a.mp4")],
        canvas_strategy=COMPOSE_CANVAS_STRATEGY_FIXED,
        target_resolution="1080x1920",
    )

    assert result == (1080, 1920)


@pytest.mark.asyncio
async def test_resolve_concat_canvas_rejects_invalid_fixed_resolution() -> None:
    handler = ComposeHandler()

    with pytest.raises(StageValidationError, match="固定目标分辨率无效"):
        await handler._resolve_concat_canvas(
            [Path("a.mp4")],
            canvas_strategy=COMPOSE_CANVAS_STRATEGY_FIXED,
            target_resolution="bad-value",
        )
