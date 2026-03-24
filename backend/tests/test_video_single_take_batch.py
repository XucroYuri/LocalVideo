import asyncio
from pathlib import Path

import pytest

from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers.base.video import VideoResult
from app.providers.video.wan2gp import get_wan2gp_video_presets
from app.providers.video_capabilities import supports_last_frame
from app.stages import task_scheduler as task_scheduler_module
from app.stages import video as video_stage_module
from app.stages.video import VideoHandler


def _write_file(path: Path, content: bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_project(tmp_path: Path) -> Project:
    return Project(
        id=1,
        title="demo",
        video_type="duo_podcast",
        output_dir=str(tmp_path),
        config={},
    )


def _make_stage() -> StageExecution:
    return StageExecution(
        project_id=1,
        stage_type=StageType.VIDEO,
        stage_number=1,
        output_data={},
    )


class _FakeDB:
    async def commit(self) -> None:
        return None


def test_wan2gp_last_frame_support_is_preset_specific() -> None:
    assert supports_last_frame("wan2gp", "ltx2_22B_distilled", "i2v") is True
    assert supports_last_frame("wan2gp", "hunyuan_1.5_i2v", "i2v") is False

    presets = get_wan2gp_video_presets()
    i2v_by_id = {item["id"]: item for item in presets["i2v_presets"]}
    assert i2v_by_id["ltx2_22B_distilled"]["supports_last_frame"] is True
    assert i2v_by_id["hunyuan_1.5_i2v"]["supports_last_frame"] is False


def test_video_single_take_uses_batch_for_static_start_end_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = VideoHandler()
    project = _make_project(tmp_path)
    stage = _make_stage()
    db = _FakeDB()

    audio_dir = tmp_path / "audio"
    frames_dir = tmp_path / "frames"
    for idx in range(3):
        _write_file(audio_dir / f"shot_{idx:03d}.mp3", b"audio")
        _write_file(frames_dir / f"frame_{idx:03d}.png", b"frame")

    async def _get_storyboard_data(_db, _project):
        return {
            "script_mode": "duo_podcast",
            "shots": [
                {"shot_index": 0, "video_prompt": "镜头一", "speaker_id": "ref_01"},
                {"shot_index": 1, "video_prompt": "镜头二", "speaker_id": "ref_02"},
                {"shot_index": 2, "video_prompt": "镜头三", "speaker_id": "ref_01"},
            ],
        }

    async def _get_content_data(_db, _project):
        return {
            "roles": [
                {"id": "ref_01", "seat_side": "right"},
                {"id": "ref_02", "seat_side": "left"},
            ]
        }

    async def _get_audio_data(_db, _project):
        return {
            "audio_assets": [
                {
                    "shot_index": idx,
                    "file_path": str(audio_dir / f"shot_{idx:03d}.mp3"),
                    "duration": 1.0,
                }
                for idx in range(3)
            ]
        }

    async def _get_frame_data(_db, _project):
        return {
            "frame_images": [
                {
                    "shot_index": idx,
                    "file_path": str(frames_dir / f"frame_{idx:03d}.png"),
                }
                for idx in range(3)
            ]
        }

    batch_calls: list[list[object]] = []
    single_calls: list[dict] = []

    class _Provider:
        async def generate(self, **kwargs):
            single_calls.append(kwargs)
            output_path = Path(kwargs["output_path"])
            _write_file(output_path, b"video-single")
            return VideoResult(
                file_path=output_path,
                duration=float(kwargs.get("duration") or 1.0),
                width=1280,
                height=720,
                fps=24,
            )

        async def generate_batch(self, tasks, progress_callback=None, status_callback=None):
            batch_calls.append(list(tasks))
            if status_callback is not None:
                await status_callback("模型加载中...")
            results = {}
            for task in tasks:
                _write_file(Path(task.output_path), b"video-batch")
                if progress_callback is not None:
                    await progress_callback(str(task.task_id), 100, str(task.output_path))
                results[str(task.task_id)] = VideoResult(
                    file_path=Path(task.output_path),
                    duration=float(task.duration or 1.0),
                    width=1280,
                    height=720,
                    fps=24,
                )
            return results

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)
    monkeypatch.setattr(handler, "_get_content_data", _get_content_data)
    monkeypatch.setattr(handler, "_get_audio_data", _get_audio_data)
    monkeypatch.setattr(handler, "_get_frame_data", _get_frame_data)
    monkeypatch.setattr(
        video_stage_module, "get_video_provider", lambda *args, **kwargs: _Provider()
    )
    monkeypatch.setattr(task_scheduler_module, "flag_modified", lambda *args, **kwargs: None)

    result = asyncio.run(
        handler.execute(
            db,
            project,
            stage,
            {
                "video_provider": "wan2gp",
                "video_wan2gp_i2v_preset": "ltx2_22B_distilled",
            },
        )
    )

    assert result.success is True
    assert len(batch_calls) == 1
    assert [str(task.task_id) for task in batch_calls[0]] == ["0", "1", "2"]
    assert batch_calls[0][0].first_frame == frames_dir / "frame_000.png"
    assert batch_calls[0][0].last_frame == frames_dir / "frame_001.png"
    assert "整个片段里右侧角色需全程说话" in batch_calls[0][0].prompt
    assert batch_calls[0][1].first_frame == frames_dir / "frame_001.png"
    assert batch_calls[0][1].last_frame == frames_dir / "frame_002.png"
    assert "整个片段里左侧角色需全程说话" in batch_calls[0][1].prompt
    assert batch_calls[0][2].first_frame == frames_dir / "frame_002.png"
    assert batch_calls[0][2].last_frame is None
    assert "整个片段里右侧角色需全程说话" in batch_calls[0][2].prompt

    assert len(single_calls) == 0

    video_assets = (result.data or {}).get("video_assets") or []
    assert len(video_assets) == 3


def test_video_stage_falls_back_to_wan2gp_when_seedance_generation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = VideoHandler()
    project = Project(
        id=1,
        title="demo",
        video_type="custom",
        output_dir=str(tmp_path),
        config={},
    )
    stage = _make_stage()
    db = _FakeDB()

    audio_path = tmp_path / "audio" / "shot_000.mp3"
    _write_file(audio_path, b"audio")

    async def _get_storyboard_data(_db, _project):
        return {
            "script_mode": "single",
            "shots": [
                {"shot_index": 0, "video_prompt": "主镜头"},
            ],
        }

    async def _get_audio_data(_db, _project):
        return {
            "audio_assets": [
                {
                    "shot_index": 0,
                    "file_path": str(audio_path),
                    "duration": 1.0,
                }
            ]
        }

    class _SeedanceProvider:
        async def generate(self, **kwargs):
            del kwargs
            raise RuntimeError("kwjm unavailable")

    class _WanProvider:
        async def generate(self, **kwargs):
            output_path = Path(kwargs["output_path"])
            _write_file(output_path, b"video-fallback")
            return VideoResult(
                file_path=output_path,
                duration=float(kwargs.get("duration") or 1.0),
                width=1280,
                height=720,
                fps=24,
            )

    def _get_provider(name: str, **kwargs):
        del kwargs
        if name == "volcengine_seedance":
            return _SeedanceProvider()
        if name == "wan2gp":
            return _WanProvider()
        raise AssertionError(f"Unexpected provider: {name}")

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)
    monkeypatch.setattr(handler, "_get_audio_data", _get_audio_data)
    monkeypatch.setattr(video_stage_module, "get_video_provider", _get_provider)
    monkeypatch.setattr(task_scheduler_module, "flag_modified", lambda *args, **kwargs: None)
    monkeypatch.setattr(video_stage_module.settings, "wan2gp_path", "/tmp/wan2gp")

    result = asyncio.run(handler.execute(db, project, stage, {"video_provider": "volcengine_seedance"}))

    assert result.success is True
    video_assets = (result.data or {}).get("video_assets") or []
    assert len(video_assets) == 1
    assert video_assets[0]["video_provider"] == "wan2gp"
    assert video_assets[0]["runtime_provider"] == "wan2gp"
