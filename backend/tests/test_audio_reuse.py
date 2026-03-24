import asyncio
import json
import shutil
from pathlib import Path

import pytest

from app.api.v1.settings import audio as settings_audio_module
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers.base.audio import AudioResult
from app.stages import audio as audio_stage_module
from app.stages._audio_cache import (
    build_audio_render_signature,
    build_audio_source_signature,
)
from app.stages.audio import AudioHandler


def _write_file(path: Path, content: bytes = b"audio") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def _fake_render_audio_from_source(
    *, source_file_path: Path, output_path: Path, speed: float
) -> Path:
    del speed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file_path, output_path)
    return output_path


async def _fake_probe_audio_duration(_path: Path) -> float:
    return 1.25


def _make_project(tmp_path: Path) -> Project:
    return Project(
        id=1,
        title="demo",
        video_type="single",
        output_dir=str(tmp_path),
        config={},
    )


def _make_stage(output_data: dict | None = None) -> StageExecution:
    return StageExecution(
        project_id=1,
        stage_type=StageType.AUDIO,
        stage_number=1,
        output_data=output_data or {},
    )


def test_render_or_reuse_audio_asset_reuses_render_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    render_path = tmp_path / "shot_000.mp3"
    source_path = tmp_path / "shot_000.source.mp3"
    _write_file(render_path)
    _write_file(source_path)

    runtime = {
        "provider_name": "edge_tts",
        "voice": "demo-voice",
        "speed": 1.3,
        "_provider_cache": {},
    }
    text = "hello world"
    source_signature = build_audio_source_signature(
        provider_name="edge_tts",
        text=text,
        config=handler._build_source_signature_config(runtime),
    )
    render_signature = build_audio_render_signature(
        audio_source_signature=source_signature,
        speed=1.3,
    )
    existing_asset = {
        "file_path": str(render_path),
        "source_file_path": str(source_path),
        "audio_source_signature": source_signature,
        "audio_render_signature": render_signature,
        "duration": 2.0,
    }

    def _should_not_create_provider(_runtime):
        raise AssertionError("provider should not be created when render cache hits")

    monkeypatch.setattr(handler, "_get_audio_provider_cached", _should_not_create_provider)

    asset, changed = asyncio.run(
        handler._render_or_reuse_audio_asset(
            existing_asset=existing_asset,
            text=text,
            render_output_path=render_path,
            runtime=runtime,
            force_regenerate=False,
        )
    )

    assert changed is False
    assert asset["file_path"] == str(render_path)
    assert asset["source_file_path"] == str(source_path)


def test_render_or_reuse_audio_asset_reuses_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    source_path = tmp_path / "shot_001.source.mp3"
    render_path = tmp_path / "shot_001.mp3"
    _write_file(source_path, b"source-audio")

    calls: list[tuple[Path, Path, float]] = []

    async def _render_stub(*, source_file_path: Path, output_path: Path, speed: float) -> Path:
        calls.append((source_file_path, output_path, speed))
        shutil.copy2(source_file_path, output_path)
        return output_path

    monkeypatch.setattr(audio_stage_module, "render_audio_from_source", _render_stub)
    monkeypatch.setattr(audio_stage_module, "probe_audio_duration", _fake_probe_audio_duration)

    def _should_not_create_provider(_runtime):
        raise AssertionError("provider should not be created when source cache hits")

    monkeypatch.setattr(handler, "_get_audio_provider_cached", _should_not_create_provider)

    current_runtime = {
        "provider_name": "edge_tts",
        "voice": "demo-voice",
        "speed": 1.0,
        "_provider_cache": {},
    }
    text = "hello world"
    source_signature = build_audio_source_signature(
        provider_name="edge_tts",
        text=text,
        config=handler._build_source_signature_config(current_runtime),
    )
    existing_asset = {
        "file_path": str(tmp_path / "old_render.mp3"),
        "source_file_path": str(source_path),
        "audio_source_signature": source_signature,
        "audio_render_signature": "old-render-signature",
    }

    asset, changed = asyncio.run(
        handler._render_or_reuse_audio_asset(
            existing_asset=existing_asset,
            text=text,
            render_output_path=render_path,
            runtime=current_runtime,
            force_regenerate=False,
        )
    )

    assert changed is True
    assert len(calls) == 1
    assert calls[0][0] == source_path
    assert asset["file_path"] == str(render_path)
    assert render_path.exists()


def test_render_or_reuse_audio_asset_regenerates_source_when_signature_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    render_path = tmp_path / "shot_002.mp3"

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, text: str, output_path: Path, **kwargs):
            del text, kwargs
            self.calls += 1
            _write_file(output_path, b"baseline")
            return AudioResult(file_path=output_path, duration=1.0)

    provider = FakeProvider()
    monkeypatch.setattr(handler, "_get_audio_provider_cached", lambda _runtime: provider)
    monkeypatch.setattr(
        audio_stage_module, "render_audio_from_source", _fake_render_audio_from_source
    )
    monkeypatch.setattr(audio_stage_module, "probe_audio_duration", _fake_probe_audio_duration)

    asset, changed = asyncio.run(
        handler._render_or_reuse_audio_asset(
            existing_asset=None,
            text="new text",
            render_output_path=render_path,
            runtime={
                "provider_name": "edge_tts",
                "voice": "demo-voice",
                "speed": 1.1,
                "_provider_cache": {},
            },
            force_regenerate=False,
        )
    )

    assert changed is True
    assert provider.calls == 1
    assert Path(asset["source_file_path"]).exists()
    assert Path(asset["file_path"]).exists()
    assert asset["audio_speed"] == 1.1


def test_render_or_reuse_audio_asset_cleans_stale_suffix_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    render_path = tmp_path / "full_script.wav"
    stale_render_path = tmp_path / "full_script.mp3"
    stale_source_path = tmp_path / "full_script.source.mp3"
    _write_file(stale_render_path, b"stale-render")
    _write_file(stale_source_path, b"stale-source")

    class FakeProvider:
        async def synthesize(self, text: str, output_path: Path, **kwargs):
            del text, kwargs
            _write_file(output_path, b"baseline-wav")
            return AudioResult(file_path=output_path, duration=1.0)

    monkeypatch.setattr(handler, "_get_audio_provider_cached", lambda _runtime: FakeProvider())
    monkeypatch.setattr(
        audio_stage_module, "render_audio_from_source", _fake_render_audio_from_source
    )
    monkeypatch.setattr(audio_stage_module, "probe_audio_duration", _fake_probe_audio_duration)

    asset, changed = asyncio.run(
        handler._render_or_reuse_audio_asset(
            existing_asset=None,
            text="full content",
            render_output_path=render_path,
            runtime={
                "provider_name": "wan2gp",
                "preset": "qwen3_tts_base",
                "model_mode": "auto",
                "alt_prompt": "",
                "audio_guide": "/storage/demo.wav",
                "duration_seconds": 600,
                "temperature": 0.9,
                "top_k": 50,
                "seed": -1,
                "split_strategy": "sentence_punct",
                "local_stitch_keep_artifacts": False,
                "speed": 1.0,
                "_provider_cache": {},
            },
            force_regenerate=False,
        )
    )

    assert changed is True
    assert Path(asset["file_path"]).exists()
    assert Path(asset["source_file_path"]).exists()
    assert not stale_render_path.exists()
    assert not stale_source_path.exists()


def test_execute_shot_audio_preserves_existing_assets_without_full_audio_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    project = _make_project(tmp_path)
    stage = _make_stage(
        {
            "audio_assets": [
                {
                    "shot_index": 1,
                    "file_path": str(tmp_path / "audio" / "shot_001.mp3"),
                    "source_file_path": str(tmp_path / "audio" / "shot_001.source.mp3"),
                    "duration": 2.0,
                    "audio_provider": "edge_tts",
                }
            ],
        }
    )

    async def _get_storyboard_data(_db, _project):
        return {
            "shots": [
                {"voice_content": "shot-a", "speaker_id": "ref_01", "speaker_name": "A"},
                {"voice_content": "shot-b", "speaker_id": "ref_02", "speaker_name": "B"},
            ]
        }

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)

    async def _render_stub(**kwargs):
        del kwargs
        return (
            {
                "file_path": str(tmp_path / "audio" / "shot_000.mp3"),
                "source_file_path": str(tmp_path / "audio" / "shot_000.source.mp3"),
                "duration": 1.0,
                "audio_source_signature": "sig-a",
                "audio_render_signature": "sig-b",
                "source_audio_speed": 1.0,
                "audio_speed": 1.0,
            },
            True,
        )

    monkeypatch.setattr(handler, "_render_or_reuse_audio_asset", _render_stub)

    async def _fake_run_scheduled_tasks(**kwargs):
        async def _noop(*_args, **_kwargs):
            return None

        spec = kwargs["task_specs"][0]
        result = await kwargs["generate_single"](spec, _noop, _noop)
        all_results = list(kwargs["all_results"])
        all_results[spec.index] = result
        return audio_stage_module.StageResult(
            success=True,
            data=kwargs["adapter"].build_final_data(
                [item for item in all_results if item is not None],
                [],
            ),
        )

    monkeypatch.setattr(audio_stage_module, "run_scheduled_tasks", _fake_run_scheduled_tasks)

    result = asyncio.run(
        handler.execute(
            None,
            project,
            stage,
            {"only_shot_index": 0, "force_regenerate": False},
        )
    )

    assert result.success is True
    assert set(result.data.keys()) >= {"audio_assets", "shot_count", "total_duration"}
    assert len(result.data["audio_assets"]) == 2


def test_execute_shot_audio_uses_role_audio_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    project = _make_project(tmp_path)
    project.video_type = "dialogue_script"
    stage = _make_stage()

    async def _get_storyboard_data(_db, _project):
        return {
            "shots": [
                {
                    "voice_content": "全文旁白测试",
                    "speaker_id": "ref_01",
                    "speaker_name": "讲述者",
                }
            ],
        }

    captured: dict[str, object] = {}

    class _Provider:
        async def synthesize(self, *, text: str, output_path: Path, voice: str, rate: str):
            captured["text"] = text
            captured["voice"] = voice
            captured["rate"] = rate
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"audio")
            return type(
                "_Result",
                (),
                {
                    "file_path": output_path,
                    "raw_file_path": None,
                    "duration": 1.0,
                },
            )()

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)
    monkeypatch.setattr(
        audio_stage_module, "get_audio_provider", lambda *args, **kwargs: _Provider()
    )

    async def _fake_run_scheduled_tasks(**kwargs):
        async def _noop(*_args, **_kwargs):
            return None

        spec = kwargs["task_specs"][0]
        result = await kwargs["generate_single"](spec, _noop, _noop)
        return audio_stage_module.StageResult(
            success=True,
            data=kwargs["adapter"].build_final_data([result], []),
        )

    monkeypatch.setattr(audio_stage_module, "run_scheduled_tasks", _fake_run_scheduled_tasks)

    result = asyncio.run(
        handler.execute(
            None,
            project,
            stage,
            {
                "audio_provider": "edge_tts",
                "voice": "demo-voice",
                "audio_role_configs": {
                    "ref_01": {
                        "voice": "override-narrator",
                        "speed": 1.3,
                    },
                },
            },
        )
    )

    assert result.success is True
    assert captured["text"] == "全文旁白测试"
    assert captured["voice"] == "override-narrator"
    assert captured["rate"] == "+30%"


def test_execute_shot_audio_uses_provider_per_speaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    project = _make_project(tmp_path)
    project.video_type = "dialogue_script"
    stage = _make_stage()

    async def _get_storyboard_data(_db, _project):
        return {
            "shots": [
                {
                    "voice_content": "旁白第一句",
                    "speaker_id": "ref_01",
                    "speaker_name": "画外音",
                },
                {
                    "voice_content": "角色第二句",
                    "speaker_id": "ref_02",
                    "speaker_name": "角色A",
                },
            ],
        }

    captured: dict[str, object] = {"calls": []}

    class _EdgeProvider:
        async def synthesize(self, *, text: str, output_path: Path, voice: str, rate: str):
            cast_calls = captured["calls"]
            assert isinstance(cast_calls, list)
            cast_calls.append(("edge_tts", text, voice, rate, output_path.suffix))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"edge-audio")
            return type(
                "_Result",
                (),
                {
                    "file_path": output_path,
                    "source_file_path": None,
                    "duration": 1.0,
                },
            )()

    class _WanProvider:
        async def synthesize(
            self,
            *,
            text: str,
            output_path: Path,
            raw_output_path: Path | None = None,
            preset: str,
            model_mode: str,
            alt_prompt: str,
            duration_seconds: int | None,
            temperature: float,
            top_k: int,
            seed: int,
            audio_guide: str,
            speed: float,
            split_strategy: str,
            local_stitch_keep_artifacts: bool,
            progress_callback=None,
            status_callback=None,
        ):
            del (
                alt_prompt,
                duration_seconds,
                temperature,
                top_k,
                seed,
                audio_guide,
                split_strategy,
                local_stitch_keep_artifacts,
            )
            if status_callback is not None:
                await status_callback("生成中...")
            if progress_callback is not None:
                await progress_callback(100)
            cast_calls = captured["calls"]
            assert isinstance(cast_calls, list)
            cast_calls.append(("wan2gp", text, preset, model_mode, speed, output_path.suffix))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"wan-audio")
            if raw_output_path is not None:
                raw_output_path.write_bytes(b"wan-raw-audio")
            return type(
                "_Result",
                (),
                {
                    "file_path": output_path,
                    "source_file_path": raw_output_path,
                    "duration": 1.2,
                },
            )()

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)
    monkeypatch.setattr(
        handler,
        "_get_audio_provider_cached",
        lambda runtime: _WanProvider() if runtime["provider_name"] == "wan2gp" else _EdgeProvider(),
    )

    async def _fake_run_scheduled_tasks(**kwargs):
        captured["scheduler_provider"] = kwargs["settings"].provider_name
        captured["allow_batch"] = kwargs["settings"].allow_batch

        async def _noop(*_args, **_kwargs):
            return None

        results = []
        for spec in kwargs["task_specs"]:
            results.append(await kwargs["generate_single"](spec, _noop, _noop))
        return audio_stage_module.StageResult(
            success=True,
            data=kwargs["adapter"].build_final_data(results, []),
        )

    monkeypatch.setattr(audio_stage_module, "run_scheduled_tasks", _fake_run_scheduled_tasks)

    result = asyncio.run(
        handler.execute(
            None,
            project,
            stage,
            {
                "audio_provider": "wan2gp",
                "audio_role_configs": {
                    "ref_01": {
                        "audio_provider": "edge_tts",
                        "voice": "zh-CN-YunxiNeural",
                        "speed": 1.3,
                    },
                    "ref_02": {
                        "audio_provider": "wan2gp",
                        "audio_wan2gp_preset": "qwen3_tts_customvoice",
                        "audio_wan2gp_model_mode": "serena",
                        "speed": 1.1,
                    },
                },
            },
        )
    )

    assert result.success is True
    assert captured["scheduler_provider"] == "mixed"
    assert captured["allow_batch"] is False
    assert captured["calls"] == [
        ("edge_tts", "旁白第一句", "zh-CN-YunxiNeural", "+30%", ".mp3"),
        ("wan2gp", "角色第二句", "qwen3_tts_customvoice", "serena", 1.1, ".wav"),
    ]
    assert result.data["audio_assets"][0]["audio_provider"] == "edge_tts"
    assert result.data["audio_assets"][0]["file_path"].endswith("shot_000.mp3")
    assert result.data["audio_assets"][1]["audio_provider"] == "wan2gp"
    assert result.data["audio_assets"][1]["file_path"].endswith("shot_001.wav")


def test_execute_wan2gp_audio_batch_allows_role_audio_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AudioHandler()
    project = _make_project(tmp_path)
    project.video_type = "dialogue_script"
    stage = _make_stage()

    async def _get_storyboard_data(_db, _project):
        return {
            "shots": [
                {
                    "voice_content": "第一句旁白",
                    "speaker_id": "ref_01",
                    "speaker_name": "讲述者",
                },
                {
                    "voice_content": "第二句角色",
                    "speaker_id": "ref_02",
                    "speaker_name": "角色一",
                },
            ],
        }

    captured: dict[str, object] = {}

    class _Provider:
        async def generate_batch(self, tasks, progress_callback=None, status_callback=None):
            captured["batch_tasks"] = tasks
            results = {}
            for task in tasks:
                task.output_path.parent.mkdir(parents=True, exist_ok=True)
                task.output_path.write_bytes(b"audio")
                raw_path = task.output_path.with_name(
                    f"{task.output_path.stem}.raw{task.output_path.suffix}"
                )
                raw_path.write_bytes(b"raw-audio")
                if progress_callback is not None:
                    await progress_callback(str(task.task_id), 100, str(task.output_path))
                results[str(task.task_id)] = AudioResult(
                    file_path=task.output_path,
                    duration=1.0,
                    source_file_path=raw_path,
                )
            return results

    monkeypatch.setattr(handler, "_get_storyboard_data", _get_storyboard_data)
    monkeypatch.setattr(
        audio_stage_module, "get_audio_provider", lambda *args, **kwargs: _Provider()
    )

    async def _fake_run_scheduled_tasks(**kwargs):
        captured["allow_batch"] = kwargs["settings"].allow_batch
        captured["task_count"] = len(kwargs["task_specs"])

        async def _noop(*_args, **_kwargs):
            return None

        batch_results = await kwargs["generate_batch"](kwargs["task_specs"], _noop, _noop)
        final_items = [
            kwargs["adapter"].build_success_result(spec, batch_results[spec.key])
            for spec in kwargs["task_specs"]
        ]
        return audio_stage_module.StageResult(
            success=True,
            data=kwargs["adapter"].build_final_data(final_items, []),
        )

    monkeypatch.setattr(audio_stage_module, "run_scheduled_tasks", _fake_run_scheduled_tasks)

    result = asyncio.run(
        handler.execute(
            None,
            project,
            stage,
            {
                "audio_provider": "wan2gp",
                "audio_wan2gp_preset": "qwen3_tts_customvoice",
                "audio_wan2gp_model_mode": "serena",
                "audio_role_configs": {
                    "ref_01": {
                        "audio_provider": "wan2gp",
                        "audio_wan2gp_preset": "qwen3_tts_customvoice",
                        "audio_wan2gp_model_mode": "serena",
                        "speed": 1.1,
                    },
                    "ref_02": {
                        "audio_provider": "wan2gp",
                        "audio_wan2gp_preset": "qwen3_tts_customvoice",
                        "audio_wan2gp_model_mode": "ryan",
                        "speed": 1.3,
                    },
                },
            },
        )
    )

    assert result.success is True
    assert captured["allow_batch"] is True
    assert captured["task_count"] == 2
    batch_tasks = captured["batch_tasks"]
    assert isinstance(batch_tasks, list)
    assert len(batch_tasks) == 2
    assert batch_tasks[0].model_mode == "serena"
    assert batch_tasks[0].speed == pytest.approx(1.1)
    assert batch_tasks[1].model_mode == "ryan"
    assert batch_tasks[1].speed == pytest.approx(1.3)


def test_audio_preview_reuses_source_for_speed_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_audio_module.settings, "storage_path", str(tmp_path), raising=False
    )
    monkeypatch.setattr(
        settings_audio_module.settings, "edge_tts_voice", "edge-demo", raising=False
    )
    monkeypatch.setattr(
        settings_audio_module, "render_audio_from_source", _fake_render_audio_from_source
    )
    monkeypatch.setattr(settings_audio_module, "probe_audio_duration", _fake_probe_audio_duration)

    class FakePreviewProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, text: str, output_path: Path, **kwargs):
            del text, kwargs
            self.calls += 1
            _write_file(output_path, b"preview")
            return AudioResult(file_path=output_path, duration=1.0)

    provider = FakePreviewProvider()
    monkeypatch.setattr(
        settings_audio_module, "get_audio_provider", lambda *args, **kwargs: provider
    )

    async def _collect_stream(rate: str) -> str:
        response = await settings_audio_module.stream_audio_preview(
            provider="edge_tts",
            input_data=json.dumps(
                {
                    "preview_text": "试听文案",
                    "edge_tts_voice": "edge-demo",
                    "edge_tts_rate": rate,
                },
                ensure_ascii=False,
            ),
            db=None,
        )
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    first_payload = asyncio.run(_collect_stream("+30%"))
    second_payload = asyncio.run(_collect_stream("+0%"))

    assert "生成完成" in first_payload
    assert "生成完成" in second_payload
    assert provider.calls == 1
