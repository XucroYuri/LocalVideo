from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

FASTER_WHISPER_DEFAULT_MODEL = "large-v3"
FASTER_WHISPER_MODELS = {
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
}
FASTER_WHISPER_MODEL_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}
EXTERNAL_RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "faster_whisper_runner.py"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FasterWhisperRuntimeAttempt:
    device: str
    compute_type: str
    python_executable: Path | None = None


@dataclass(slots=True)
class FasterWhisperTranscriptionResult:
    model: str
    device: str
    compute_type: str
    utterance_count: int
    word_count: int
    preview_text: str
    utterances: list[dict[str, Any]]
    words: list[dict[str, Any]]
    elapsed_ms: int


def resolve_faster_whisper_model_name(model: str | None) -> str:
    candidate = (
        str(model or settings.faster_whisper_model or FASTER_WHISPER_DEFAULT_MODEL).strip().lower()
    )
    if candidate in FASTER_WHISPER_MODELS:
        return candidate
    raise ValueError(f"faster-whisper 模型无效。可选值: {', '.join(sorted(FASTER_WHISPER_MODELS))}")


def resolve_local_model_python_path(
    configured_path: str | None = None,
    *,
    required: bool = False,
) -> Path | None:
    candidate = str(configured_path or settings.local_model_python_path or "").strip()
    if not candidate:
        if required:
            raise RuntimeError("GPU 模式下请先在“本地模型依赖”中配置共享 Python 路径。")
        return None

    python_path = Path(candidate).expanduser()
    if not python_path.exists() or not python_path.is_file():
        raise RuntimeError(f"共享 Python 路径无效（文件不存在）: {python_path}")
    return python_path


def resolve_faster_whisper_runtime_attempts() -> list[FasterWhisperRuntimeAttempt]:
    profile = str(settings.deployment_profile or "").strip().lower()
    if profile == "gpu":
        python_path = resolve_local_model_python_path(required=True)
        return [
            FasterWhisperRuntimeAttempt(
                device="cuda",
                compute_type="float16",
                python_executable=python_path,
            ),
        ]

    return [
        FasterWhisperRuntimeAttempt(
            device="cpu",
            compute_type="int8",
            python_executable=None,
        )
    ]


def _normalize_timestamp(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return parsed if parsed >= 0 else fallback


def _resolve_hf_hub_cache_dir() -> Path:
    explicit_cache = str(
        os.environ.get("HUGGINGFACE_HUB_CACHE") or os.environ.get("HF_HUB_CACHE") or ""
    ).strip()
    if explicit_cache:
        return Path(explicit_cache).expanduser()

    hf_home = str(os.environ.get("HF_HOME") or "").strip()
    if hf_home:
        return Path(hf_home).expanduser() / "hub"

    return Path.home() / ".cache" / "huggingface" / "hub"


def _is_valid_cached_model_snapshot(path: Path) -> bool:
    required_files = ("config.json", "model.bin", "tokenizer.json")
    return path.is_dir() and all((path / name).exists() for name in required_files)


def resolve_cached_faster_whisper_model_path(model_name: str) -> Path | None:
    repo_id = FASTER_WHISPER_MODEL_REPOS.get(model_name)
    if not repo_id:
        return None

    repo_cache_dir = _resolve_hf_hub_cache_dir() / f"models--{repo_id.replace('/', '--')}"
    snapshots_dir = repo_cache_dir / "snapshots"
    if not snapshots_dir.exists() or not snapshots_dir.is_dir():
        return None

    refs_main = repo_cache_dir / "refs" / "main"
    preferred_snapshot = ""
    with contextlib.suppress(OSError):
        preferred_snapshot = refs_main.read_text(encoding="utf-8").strip()
    if preferred_snapshot:
        candidate = snapshots_dir / preferred_snapshot
        if _is_valid_cached_model_snapshot(candidate):
            return candidate

    snapshots = sorted((path for path in snapshots_dir.iterdir() if path.is_dir()), key=lambda p: p.name)
    if snapshots:
        for candidate in reversed(snapshots):
            if _is_valid_cached_model_snapshot(candidate):
                return candidate
    return None


def _build_result(payload: dict[str, Any]) -> FasterWhisperTranscriptionResult:
    raw_utterances = payload.get("utterances")
    if not isinstance(raw_utterances, list):
        raw_utterances = payload.get("segments")
    utterances = list(raw_utterances or [])

    return FasterWhisperTranscriptionResult(
        model=str(payload.get("model") or "").strip(),
        device=str(payload.get("device") or "").strip(),
        compute_type=str(payload.get("compute_type") or "").strip(),
        utterance_count=int(payload.get("utterance_count") or payload.get("segment_count") or 0),
        word_count=int(payload.get("word_count") or 0),
        preview_text=str(payload.get("preview_text") or "").strip(),
        utterances=utterances,
        words=list(payload.get("words") or []),
        elapsed_ms=int(payload.get("elapsed_ms") or 0),
    )


def _run_transcription_sync(
    *,
    audio_path: Path,
    model_name: str,
    runtime_attempt: FasterWhisperRuntimeAttempt,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> FasterWhisperTranscriptionResult:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - dependency validated separately
        raise RuntimeError("后端主环境未安装 faster-whisper。") from exc

    started = time.perf_counter()
    cached_model_path = resolve_cached_faster_whisper_model_path(model_name)
    model_source = str(cached_model_path) if cached_model_path is not None else model_name
    model = WhisperModel(
        model_source,
        device=runtime_attempt.device,
        compute_type=runtime_attempt.compute_type,
        local_files_only=False,
    )
    utterances_iter, _ = model.transcribe(str(audio_path), word_timestamps=True)

    payload_utterances: list[dict[str, Any]] = []
    payload_words: list[dict[str, Any]] = []
    preview_tokens: list[str] = []

    for utterance_index, utterance in enumerate(utterances_iter):
        seg_text = (getattr(utterance, "text", "") or "").strip()
        seg_start = _normalize_timestamp(getattr(utterance, "start", 0.0), 0.0)
        seg_end = _normalize_timestamp(
            getattr(utterance, "end", seg_start + 0.01), seg_start + 0.01
        )
        if seg_end <= seg_start:
            seg_end = seg_start + 0.01

        utterance_words: list[dict[str, Any]] = []
        for word in getattr(utterance, "words", None) or []:
            word_text = (getattr(word, "word", "") or "").strip()
            if not word_text:
                continue
            word_start = _normalize_timestamp(getattr(word, "start", seg_start), seg_start)
            word_end = _normalize_timestamp(
                getattr(word, "end", word_start + 0.01), word_start + 0.01
            )
            if word_end <= word_start:
                word_end = word_start + 0.01
            payload = {
                "word": word_text,
                "start": word_start,
                "end": word_end,
                "utterance_index": utterance_index,
            }
            utterance_words.append(payload)
            payload_words.append(payload)

        payload_utterances.append(
            {
                "text": seg_text,
                "start": seg_start,
                "end": seg_end,
                "words": utterance_words,
            }
        )
        if seg_text:
            preview_tokens.append(seg_text)
        if progress_callback is not None:
            progress_callback(
                {
                    "utterance_index": utterance_index + 1,
                    "utterance_end": seg_end,
                }
            )

    preview_text = " ".join(preview_tokens).strip()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return FasterWhisperTranscriptionResult(
        model=model_name,
        device=runtime_attempt.device,
        compute_type=runtime_attempt.compute_type,
        utterance_count=len(payload_utterances),
        word_count=len(payload_words),
        preview_text=preview_text,
        utterances=payload_utterances,
        words=payload_words,
        elapsed_ms=elapsed_ms,
    )


def _trim_output_tail(lines: list[str], *, limit: int = 20) -> str:
    if not lines:
        return "<no output>"
    return "\n".join(lines[-limit:])


def _read_log_file_tail(log_path: Path, *, limit: int = 40) -> str:
    if not log_path.exists() or not log_path.is_file():
        return "<runner log missing>"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:  # noqa: BLE001
        return f"<runner log unreadable: {exc}>"
    if not lines:
        return "<runner log empty>"
    return "\n".join(lines[-limit:])


def _read_result_payload(result_path: Path) -> dict[str, Any]:
    if not result_path.exists() or not result_path.is_file():
        raise RuntimeError(f"runner result file missing: {result_path}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"runner result file invalid: {result_path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"runner result payload is not an object: {result_path}")
    return payload


def _cleanup_runner_artifacts(*paths: Path) -> None:
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


async def _consume_process_stderr(
    stream: asyncio.StreamReader | None,
    stderr_tail: list[str],
) -> None:
    if stream is None:
        return
    while True:
        raw_line = await stream.readline()
        if not raw_line:
            break
        line = raw_line.decode(errors="ignore").strip()
        if not line:
            continue
        stderr_tail.append(line)
        if len(stderr_tail) > 120:
            del stderr_tail[:-120]


async def _run_transcription_external(
    *,
    audio_path: Path,
    model_name: str,
    runtime_attempt: FasterWhisperRuntimeAttempt,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> FasterWhisperTranscriptionResult:
    python_path = runtime_attempt.python_executable
    if python_path is None:
        raise RuntimeError("GPU 模式缺少共享 Python 路径。")
    if not EXTERNAL_RUNNER_PATH.exists():
        raise RuntimeError(f"缺少 faster-whisper runner 脚本: {EXTERNAL_RUNNER_PATH}")
    invocation_id = f"fw_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    runner_log_path = (
        EXTERNAL_RUNNER_PATH.resolve().parents[1]
        / "storage"
        / "logs"
        / "faster-whisper"
        / f"{invocation_id}.log"
    )
    runner_result_path = (
        EXTERNAL_RUNNER_PATH.resolve().parents[1]
        / "storage"
        / "logs"
        / "faster-whisper"
        / f"{invocation_id}.result.json"
    )
    cached_model_path = resolve_cached_faster_whisper_model_path(model_name)

    process = await asyncio.create_subprocess_exec(
        str(python_path),
        "-u",
        str(EXTERNAL_RUNNER_PATH),
        "--audio-path",
        str(audio_path),
        "--model-name",
        model_name,
        "--device",
        runtime_attempt.device,
        "--compute-type",
        runtime_attempt.compute_type,
        "--invocation-id",
        invocation_id,
        "--result-path",
        str(runner_result_path),
        *(["--model-path", str(cached_model_path)] if cached_model_path is not None else []),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_tail: list[str] = []
    stderr_tail: list[str] = []
    result_payload: dict[str, Any] | None = None
    last_progress_utterance_index: int | None = None
    last_progress_utterance_end: float | None = None
    stderr_task = asyncio.create_task(_consume_process_stderr(process.stderr, stderr_tail))

    try:
        while True:
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            text = raw_line.decode(errors="ignore").strip()
            if not text:
                continue
            stdout_tail.append(text)
            if len(stdout_tail) > 40:
                del stdout_tail[:-40]
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            event_type = str(payload.get("type") or "").strip().lower()
            if event_type == "progress" and on_progress is not None:
                utterance_index = payload.get("utterance_index", payload.get("segment_index"))
                utterance_end = payload.get("utterance_end", payload.get("segment_end"))
                try:
                    last_progress_utterance_index = int(utterance_index)
                except (TypeError, ValueError):
                    last_progress_utterance_index = None
                try:
                    last_progress_utterance_end = float(utterance_end)
                except (TypeError, ValueError):
                    last_progress_utterance_end = None
                await on_progress(
                    {
                        "utterance_index": utterance_index,
                        "utterance_end": utterance_end,
                    }
                )
            elif event_type == "progress":
                utterance_index = payload.get("utterance_index", payload.get("segment_index"))
                utterance_end = payload.get("utterance_end", payload.get("segment_end"))
                try:
                    last_progress_utterance_index = int(utterance_index)
                except (TypeError, ValueError):
                    last_progress_utterance_index = None
                try:
                    last_progress_utterance_end = float(utterance_end)
                except (TypeError, ValueError):
                    last_progress_utterance_end = None
            elif event_type == "result":
                raw_result = payload.get("result")
                if isinstance(raw_result, dict):
                    result_payload = raw_result
                    continue
                raw_result_path = str(payload.get("result_path") or "").strip()
                if raw_result_path:
                    result_payload = _read_result_payload(Path(raw_result_path))
                else:
                    result_payload = _read_result_payload(runner_result_path)

        return_code = await process.wait()
        await stderr_task
    finally:
        if not stderr_task.done():
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task

    if return_code != 0:
        error_preview = _trim_output_tail(stderr_tail or stdout_tail)
        runner_log_preview = _read_log_file_tail(runner_log_path)
        progress_preview = "无"
        if last_progress_utterance_index is not None or last_progress_utterance_end is not None:
            progress_preview = (
                f"utterance_index={last_progress_utterance_index or '-'} "
                f"utterance_end={last_progress_utterance_end if last_progress_utterance_end is not None else '-'}"
            )
        logger.warning(
            "[FasterWhisperRuntime][ExternalRunner] nonzero exit"
            " audio=%s model=%s device=%s compute_type=%s python=%s invocation_id=%s"
            " last_progress=%s output=%s runner_log=%s tail=%s",
            audio_path,
            model_name,
            runtime_attempt.device,
            runtime_attempt.compute_type,
            python_path,
            invocation_id,
            progress_preview,
            error_preview.replace("\n", " | "),
            runner_log_path,
            runner_log_preview.replace("\n", " | "),
        )
        raise RuntimeError(
            "外部 faster-whisper 运行失败"
            f" (device={runtime_attempt.device}, compute_type={runtime_attempt.compute_type})\n"
            f"Python: {python_path}\n"
            f"Invocation: {invocation_id}\n"
            f"Runner log: {runner_log_path}\n"
            f"Runner result: {runner_result_path}\n"
            f"最后进度: {progress_preview}\n"
            f"输出预览:\n{error_preview}\n"
            f"Runner日志预览:\n{runner_log_preview}"
        )
    if result_payload is None:
        raise RuntimeError(
            "外部 faster-whisper 未返回结果"
            f" (device={runtime_attempt.device}, compute_type={runtime_attempt.compute_type})"
        )
    result = _build_result(result_payload)
    _cleanup_runner_artifacts(runner_result_path, runner_log_path)
    return result


async def _run_transcription_internal(
    *,
    audio_path: Path,
    model_name: str,
    runtime_attempt: FasterWhisperRuntimeAttempt,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> FasterWhisperTranscriptionResult:
    if on_progress is None:
        return await asyncio.to_thread(
            _run_transcription_sync,
            audio_path=audio_path,
            model_name=model_name,
            runtime_attempt=runtime_attempt,
        )

    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def _push_progress(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, payload)

    worker = asyncio.create_task(
        asyncio.to_thread(
            _run_transcription_sync,
            audio_path=audio_path,
            model_name=model_name,
            runtime_attempt=runtime_attempt,
            progress_callback=_push_progress,
        )
    )
    worker.add_done_callback(lambda _: loop.call_soon_threadsafe(progress_queue.put_nowait, None))

    try:
        while True:
            payload = await progress_queue.get()
            if payload is None:
                break
            await on_progress(payload)
    finally:
        if not worker.done():
            loop.call_soon_threadsafe(progress_queue.put_nowait, None)

    return await worker


async def transcribe_with_faster_whisper(
    audio_path: Path,
    *,
    model: str | None = None,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> FasterWhisperTranscriptionResult:
    model_name = resolve_faster_whisper_model_name(model)
    runtime_attempts = resolve_faster_whisper_runtime_attempts()
    errors: list[str] = []

    for runtime_attempt in runtime_attempts:
        logger.info(
            "[FasterWhisperRuntime] start audio=%s model=%s device=%s compute_type=%s external=%s",
            audio_path,
            model_name,
            runtime_attempt.device,
            runtime_attempt.compute_type,
            bool(runtime_attempt.python_executable),
        )
        try:
            if runtime_attempt.python_executable is not None:
                result = await _run_transcription_external(
                    audio_path=audio_path,
                    model_name=model_name,
                    runtime_attempt=runtime_attempt,
                    on_progress=on_progress,
                )
            else:
                result = await _run_transcription_internal(
                    audio_path=audio_path,
                    model_name=model_name,
                    runtime_attempt=runtime_attempt,
                    on_progress=on_progress,
                )
            logger.info(
                "[FasterWhisperRuntime] done audio=%s model=%s device=%s compute_type=%s utterances=%s words=%s elapsed_ms=%s",
                audio_path,
                model_name,
                runtime_attempt.device,
                runtime_attempt.compute_type,
                result.utterance_count,
                result.word_count,
                result.elapsed_ms,
            )
            return result
        except Exception as exc:
            error_text = str(exc).replace("\n", " | ")
            logger.warning(
                "[FasterWhisperRuntime] failed audio=%s model=%s device=%s compute_type=%s error=%s",
                audio_path,
                model_name,
                runtime_attempt.device,
                runtime_attempt.compute_type,
                error_text,
            )
            errors.append(
                f"device={runtime_attempt.device}, compute_type={runtime_attempt.compute_type}: {exc}"
            )

    joined_errors = "\n\n".join(errors) if errors else "未知错误"
    raise RuntimeError(f"faster-whisper 运行失败，已尝试所有运行方案：\n{joined_errors}")
