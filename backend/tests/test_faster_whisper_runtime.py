from pathlib import Path

import pytest

from app.config import settings
from app.services.faster_whisper_runtime import (
    _build_result,
    resolve_cached_faster_whisper_model_path,
    resolve_faster_whisper_runtime_attempts,
)


def test_resolve_faster_whisper_runtime_attempts_cpu_uses_builtin_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deployment_profile", "cpu", raising=False)
    monkeypatch.setattr(settings, "local_model_python_path", None, raising=False)

    attempts = resolve_faster_whisper_runtime_attempts()

    assert len(attempts) == 1
    assert attempts[0].device == "cpu"
    assert attempts[0].compute_type == "int8"
    assert attempts[0].python_executable is None


def test_resolve_faster_whisper_runtime_attempts_gpu_requires_shared_python_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deployment_profile", "gpu", raising=False)
    monkeypatch.setattr(settings, "local_model_python_path", None, raising=False)

    with pytest.raises(RuntimeError, match="共享 Python 路径"):
        resolve_faster_whisper_runtime_attempts()


def test_resolve_faster_whisper_runtime_attempts_gpu_uses_shared_python_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python_path = tmp_path / "bin" / "python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("#!/usr/bin/env python\n")

    monkeypatch.setattr(settings, "deployment_profile", "gpu", raising=False)
    monkeypatch.setattr(settings, "local_model_python_path", str(python_path), raising=False)

    attempts = resolve_faster_whisper_runtime_attempts()

    assert [(one.device, one.compute_type) for one in attempts] == [
        ("cuda", "float16"),
    ]
    assert all(one.python_executable == python_path for one in attempts)


def test_resolve_cached_faster_whisper_model_path_uses_hf_cache_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hub_cache = tmp_path / "hub"
    snapshot = (
        hub_cache
        / "models--Systran--faster-whisper-large-v3"
        / "snapshots"
        / "abc123"
    )
    (hub_cache / "models--Systran--faster-whisper-large-v3" / "refs").mkdir(parents=True)
    snapshot.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (snapshot / name).write_text("stub", encoding="utf-8")
    (hub_cache / "models--Systran--faster-whisper-large-v3" / "refs" / "main").write_text(
        "abc123\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(hub_cache))

    assert resolve_cached_faster_whisper_model_path("large-v3") == snapshot


def test_build_result_accepts_external_runner_segment_aliases() -> None:
    result = _build_result(
        {
            "model": "large-v3",
            "device": "cuda",
            "compute_type": "float16",
            "segment_count": 2,
            "word_count": 3,
            "preview_text": "test",
            "segments": [{"text": "a"}, {"text": "b"}],
            "words": [{"word": "x"}],
            "elapsed_ms": 12,
        }
    )

    assert result.utterance_count == 2
    assert result.utterances == [{"text": "a"}, {"text": "b"}]
    assert result.word_count == 3
