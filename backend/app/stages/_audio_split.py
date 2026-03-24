import asyncio
import base64
import difflib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings
from app.core.errors import StageRuntimeError, StageValidationError
from app.services.faster_whisper_runtime import (
    resolve_faster_whisper_model_name,
    transcribe_with_faster_whisper,
)
from app.stages.subtitle import generate_srt_content

try:
    from opencc import OpenCC
except Exception:  # pragma: no cover - optional dependency
    OpenCC = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

PUNCTUATION_PATTERN = re.compile(r"[，。！？；：,.!?;:、''()（）【】\[\]《》<>～~…—\-\s]")
SHOT_FILE_PATTERN = re.compile(r"^shot_(\d{3})\.")
MATCH_CLEAN_PATTERN = re.compile(r"[^\w\u4e00-\u9fff]+", flags=re.UNICODE)
SRT_SENTENCE_BREAK_PATTERN = re.compile(r"[。！？!?；;，,、…—]$")
DIGIT_NORMALIZE_PATTERN = re.compile(
    r"[0-9零〇○一二两兩三四五六七八九十百千万萬亿億壹贰貳叁參肆伍陆陸柒捌玖拾佰仟]+"
)

SRT_MAX_CHARS_PER_LINE = 12
SRT_MAX_WORD_GAP_SECONDS = 0.45
AUDIO_SPLIT_MODE_BASIC = "basic"
AUDIO_SPLIT_MODE_FASTER_WHISPER = "faster_whisper"
SUPPORTED_AUDIO_SPLIT_MODES = {
    AUDIO_SPLIT_MODE_BASIC,
    AUDIO_SPLIT_MODE_FASTER_WHISPER,
}
FASTER_WHISPER_DEFAULT_MODEL = "large-v3"
FASTER_WHISPER_TRANSCRIBE_TIMEOUT_SECONDS = 60 * 20
FASTER_WHISPER_PROGRESS_PREFIX = "__YF_WHISPER_PROGRESS__"
FASTER_WHISPER_PROGRESS_HEARTBEAT_SECONDS = 1.0
VOLCENGINE_ASR_DEFAULT_RESOURCE_ID = "volc.seedasr.auc"
VOLCENGINE_ASR_SUBMIT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLCENGINE_ASR_QUERY_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
VOLCENGINE_ASR_SUCCESS_STATUS_CODE = 20000000
VOLCENGINE_ASR_PENDING_STATUS_CODES = {20000001, 20000002}
VOLCENGINE_ASR_SILENCE_STATUS_CODE = 20000003
VOLCENGINE_ASR_QUERY_TIMEOUT_SECONDS = 300.0
VOLCENGINE_ASR_QUERY_POLL_SECONDS = 1.0
VOLCENGINE_ASR_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
SPEECH_RECOGNITION_PROVIDER_FASTER_WHISPER = "faster_whisper"
SPEECH_RECOGNITION_PROVIDER_VOLCENGINE = "volcengine_asr"
SPEECH_MODEL_BINDING_SEPARATOR = "::"
ALIGN_LOG_TEXT_PREVIEW = 120
ALIGNMENT_MIN_COVERAGE = 0.65
BOUNDARY_BLEND_PREVIOUS_END = 0.0
BOUNDARY_BLEND_CURRENT_START = 1.0

TRADITIONAL_TO_SIMPLIFIED_FALLBACK_MAP = str.maketrans(
    {
        "雜": "杂",
        "這": "这",
        "個": "个",
        "裡": "里",
        "們": "们",
        "說": "说",
        "為": "为",
        "來": "来",
        "還": "还",
        "眾": "众",
        "後": "后",
        "種": "种",
        "麥": "麦",
        "廣": "广",
        "邊": "边",
        "條": "条",
        "錢": "钱",
        "頭": "头",
        "腦": "脑",
        "覺": "觉",
        "門": "门",
        "塊": "块",
    }
)

OPENCC_T2S = None
if OpenCC is not None:
    try:
        OPENCC_T2S = OpenCC("t2s")
    except Exception:
        OPENCC_T2S = None


def _build_missing_binary_error(binary_name: str) -> StageRuntimeError:
    return StageRuntimeError(
        f"未找到可执行命令 `{binary_name}`（系统 PATH 中不存在）。"
        "音频切分依赖 ffmpeg/ffprobe。"
        "请先安装 ffmpeg（含 ffprobe），并确保命令行可直接执行。"
    )


def count_effective_chars(text: str) -> int:
    return len(PUNCTUATION_PATTERN.sub("", text or ""))


def _normalize_match_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    if OPENCC_T2S is not None:
        try:
            value = OPENCC_T2S.convert(value)
        except Exception:
            value = value.translate(TRADITIONAL_TO_SIMPLIFIED_FALLBACK_MAP)
    else:
        value = value.translate(TRADITIONAL_TO_SIMPLIFIED_FALLBACK_MAP)
    value = value.lower()
    value = DIGIT_NORMALIZE_PATTERN.sub("0", value)
    return MATCH_CLEAN_PATTERN.sub("", value)


def _build_shot_duration_plan(
    total_duration: float, shots: list[dict[str, Any]]
) -> list[tuple[float, float]]:
    if not shots:
        return []

    safe_total_duration = max(0.0, float(total_duration or 0.0))
    if safe_total_duration <= 0:
        return [(0.0, 0.0) for _ in shots]

    char_counts = [
        max(0, count_effective_chars(str(shot.get("voice_content") or ""))) for shot in shots
    ]
    total_chars = sum(char_counts)
    if total_chars <= 0:
        char_counts = [1 for _ in shots]
        total_chars = len(shots)

    plan: list[tuple[float, float]] = []
    start = 0.0
    for index, char_count in enumerate(char_counts):
        if index == len(char_counts) - 1:
            duration = max(0.0, safe_total_duration - start)
        else:
            duration = safe_total_duration * (char_count / total_chars)
            duration = max(0.0, duration)
        plan.append((start, duration))
        start += duration

    return plan


async def probe_audio_duration(file_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise _build_missing_binary_error("ffprobe") from e
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0.0

    try:
        payload = json.loads(stdout.decode(errors="ignore") or "{}")
    except Exception:
        return 0.0

    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    try:
        return max(0.0, float(format_info.get("duration") or 0.0))
    except (TypeError, ValueError):
        return 0.0


async def _slice_audio_clip(
    input_path: Path,
    output_path: Path,
    start: float,
    duration: float,
) -> None:
    safe_start = max(0.0, float(start or 0.0))
    safe_duration = max(0.01, float(duration or 0.0))

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{safe_start:.6f}",
        "-i",
        str(input_path),
        "-t",
        f"{safe_duration:.6f}",
        "-vn",
        str(output_path),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise _build_missing_binary_error("ffmpeg") from e
    _, stderr = await process.communicate()
    if process.returncode != 0:
        error_text = stderr.decode(errors="ignore").strip()
        raise StageRuntimeError(f"ffmpeg split failed (code={process.returncode}): {error_text}")
    if not output_path.exists():
        raise StageRuntimeError("ffmpeg split finished but output file was not created")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_progress_payloads_from_stderr_line(line: str) -> list[dict[str, Any]]:
    normalized = str(line or "")
    if not normalized or FASTER_WHISPER_PROGRESS_PREFIX not in normalized:
        return []

    decoder = json.JSONDecoder()
    payloads: list[dict[str, Any]] = []
    parts = normalized.split(FASTER_WHISPER_PROGRESS_PREFIX)
    for part in parts[1:]:
        candidate = part.lstrip()
        if not candidate:
            continue
        start_index = candidate.find("{")
        if start_index < 0:
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[start_index:])
        except Exception:  # noqa: BLE001
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _extract_word_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_words = payload.get("words") if isinstance(payload.get("words"), list) else None
    if raw_words is None and isinstance(payload.get("utterances"), list):
        merged_words: list[Any] = []
        for utterance in payload.get("utterances", []):
            if isinstance(utterance, dict) and isinstance(utterance.get("words"), list):
                merged_words.extend(utterance.get("words") or [])
        if merged_words:
            raw_words = merged_words

    words: list[dict[str, Any]] = []
    if isinstance(raw_words, list):
        for item in raw_words:
            if not isinstance(item, dict):
                continue
            text = str(item.get("word") or item.get("text") or "").strip()
            if not text:
                continue
            start = _safe_float(item.get("start"))
            end = _safe_float(item.get("end"))
            if end <= start:
                end = start + 0.01
            normalized = _normalize_match_text(text)
            if not normalized:
                continue
            utterance_index: int | None = None
            try:
                raw_utterance_index = item.get("utterance_index")
                if raw_utterance_index is not None:
                    utterance_index = int(raw_utterance_index)
            except (TypeError, ValueError):
                utterance_index = None
            word_payload: dict[str, Any] = {
                "word": text,
                "start": start,
                "end": end,
                "normalized": normalized,
            }
            if utterance_index is not None and utterance_index >= 0:
                word_payload["utterance_index"] = utterance_index
            words.append(word_payload)

    if words:
        words.sort(key=lambda item: (item.get("start", 0.0), item.get("end", 0.0)))
        return words

    if isinstance(payload.get("utterances"), list):
        for utterance_index, utterance in enumerate(payload.get("utterances", [])):
            if not isinstance(utterance, dict):
                continue
            text = str(utterance.get("text") or "").strip()
            if not text:
                continue
            start = _safe_float(utterance.get("start"))
            end = _safe_float(utterance.get("end"))
            if end <= start:
                end = start + 0.01
            normalized = _normalize_match_text(text)
            if not normalized:
                continue
            words.append(
                {
                    "word": text,
                    "start": start,
                    "end": end,
                    "normalized": normalized,
                    "utterance_index": utterance_index,
                }
            )

    words.sort(key=lambda item: (item.get("start", 0.0), item.get("end", 0.0)))
    normalized_words = words
    logger.info(
        "[AudioSplit] faster-whisper 规范化词流完成: normalized_words=%d",
        len(normalized_words),
    )
    return normalized_words


def _extract_utterance_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    utterances: list[dict[str, Any]] = []
    raw_utterances = payload.get("utterances")
    if not isinstance(raw_utterances, list):
        return utterances

    for item in raw_utterances:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        start = _safe_float(item.get("start"))
        end = _safe_float(item.get("end"))
        if end <= start:
            end = start + 0.01
        words = item.get("words")
        word_count = len(words) if isinstance(words, list) else 0
        utterances.append(
            {
                "text": text,
                "start": start,
                "end": end,
                "word_count": word_count,
            }
        )
    utterances.sort(key=lambda item: (item.get("start", 0.0), item.get("end", 0.0)))
    return utterances


def _tail_process_text(stdout: bytes, stderr: bytes, limit: int = 24) -> str:
    lines: list[str] = []
    if stdout:
        lines.extend(stdout.decode(errors="ignore").splitlines())
    if stderr:
        lines.extend(stderr.decode(errors="ignore").splitlines())
    if not lines:
        return "<no output>"
    return "\n".join(lines[-limit:])


def _resolve_faster_whisper_model_name() -> str:
    return resolve_faster_whisper_model_name(settings.faster_whisper_model)


def _normalize_speech_recognition_provider(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == SPEECH_RECOGNITION_PROVIDER_VOLCENGINE:
        return SPEECH_RECOGNITION_PROVIDER_VOLCENGINE
    return SPEECH_RECOGNITION_PROVIDER_FASTER_WHISPER


def _parse_default_speech_binding(value: str | None) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    if SPEECH_MODEL_BINDING_SEPARATOR not in text:
        return "", text
    provider, model = text.split(SPEECH_MODEL_BINDING_SEPARATOR, 1)
    return _normalize_speech_recognition_provider(provider), str(model or "").strip()


def _resolve_speech_runtime(
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    requested_provider = _normalize_speech_recognition_provider(provider)
    requested_model = str(model or "").strip()
    picked_from_default_binding = False
    if not provider and not requested_model:
        default_provider, default_model = _parse_default_speech_binding(
            settings.default_speech_recognition_model
        )
        if default_provider:
            requested_provider = default_provider
        if default_model:
            requested_model = default_model
            picked_from_default_binding = True

    if not provider and not picked_from_default_binding:
        requested_provider = _normalize_speech_recognition_provider(
            settings.default_speech_recognition_provider or requested_provider
        )

    if requested_provider == SPEECH_RECOGNITION_PROVIDER_VOLCENGINE:
        resolved_model = (
            requested_model
            or str(
                settings.speech_volcengine_resource_id or VOLCENGINE_ASR_DEFAULT_RESOURCE_ID
            ).strip()
        )
        if not resolved_model:
            resolved_model = VOLCENGINE_ASR_DEFAULT_RESOURCE_ID
        return requested_provider, resolved_model

    resolved_model = requested_model or _resolve_faster_whisper_model_name()
    return SPEECH_RECOGNITION_PROVIDER_FASTER_WHISPER, resolved_model


def _preview_text(text: str, limit: int = ALIGN_LOG_TEXT_PREVIEW) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


async def _transcribe_audio_words_faster_whisper(
    audio_path: Path,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    *,
    model_name_override: str | None = None,
) -> list[dict[str, Any]]:
    if not audio_path.exists():
        logger.warning("[AudioSplit] 音频文件不存在，跳过转写: %s", audio_path)
        return []

    async def _emit_progress(
        *,
        phase: str,
        current_seconds: float,
        total_seconds: float,
        utterance_index: int | None = None,
    ) -> None:
        if on_progress is None:
            return
        total = max(0.0, float(total_seconds or 0.0))
        current = max(0.0, float(current_seconds or 0.0))
        progress = 0.0
        if total > 0:
            progress = max(0.0, min(1.0, current / total))
        payload: dict[str, Any] = {
            "phase": phase,
            "current_seconds": current,
            "total_seconds": total,
            "progress": progress,
        }
        if utterance_index is not None:
            payload["utterance_index"] = int(utterance_index)
        try:
            await on_progress(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AudioSplit] transcribe progress callback failed: %s", exc)

    total_duration = await probe_audio_duration(audio_path)
    await _emit_progress(phase="start", current_seconds=0.0, total_seconds=total_duration)

    model_name = str(model_name_override or _resolve_faster_whisper_model_name()).strip()
    if not model_name:
        model_name = _resolve_faster_whisper_model_name()
    logger.info(
        "[AudioSplit] faster-whisper 转写开始: audio=%s model=%s",
        audio_path,
        model_name,
    )
    try:
        result = await asyncio.wait_for(
            transcribe_with_faster_whisper(
                audio_path,
                model=model_name,
                on_progress=lambda payload: _emit_progress(
                    phase="transcribing",
                    current_seconds=_safe_float(payload.get("utterance_end")),
                    total_seconds=total_duration,
                    utterance_index=int(_safe_float(payload.get("utterance_index"), 0)) or None,
                ),
            ),
            timeout=FASTER_WHISPER_TRANSCRIBE_TIMEOUT_SECONDS,
        )
    except TimeoutError as e:
        raise StageRuntimeError(
            "faster-whisper 转写超时，请检查模型大小、音频长度或运行时环境。"
        ) from e
    except Exception as exc:
        raise StageRuntimeError(f"faster-whisper 转写失败: {exc}") from exc

    utterances = result.utterances
    words = result.words
    first_start = _safe_float(utterances[0].get("start")) if utterances else 0.0
    last_end = _safe_float(utterances[-1].get("end")) if utterances else 0.0
    logger.info(
        "[AudioSplit] faster-whisper 识别完成: utterances=%d words=%d span=%.2fs(%.3f->%.3f)",
        len(utterances),
        len(words),
        max(0.0, last_end - first_start),
        first_start,
        last_end,
    )
    await _emit_progress(
        phase="done",
        current_seconds=last_end if last_end > 0 else total_duration,
        total_seconds=total_duration if total_duration > 0 else last_end,
    )
    normalized_words = _extract_word_items(
        {
            "words": words,
            "utterances": utterances,
        }
    )
    logger.info(
        "[AudioSplit] faster-whisper 规范化词流完成: normalized_words=%d",
        len(normalized_words),
    )
    return normalized_words


def _resolve_volcengine_time_scale(result: dict[str, Any], total_duration: float) -> float:
    additions = result.get("additions")
    duration_candidate = None
    if isinstance(additions, dict):
        duration_candidate = additions.get("duration")
    duration_value = max(0.0, _safe_float(duration_candidate))
    if duration_value > 0 and total_duration > 0:
        duration_seconds = duration_value / 1000.0
        if abs(duration_seconds - total_duration) <= max(2.0, total_duration * 0.2):
            return 0.001

    threshold = max(total_duration * 2.0, 120.0)
    utterances = result.get("utterances")
    if isinstance(utterances, list):
        for utterance in utterances[:3]:
            if not isinstance(utterance, dict):
                continue
            candidates = [
                utterance.get("start_time"),
                utterance.get("end_time"),
                utterance.get("start"),
                utterance.get("end"),
            ]
            words = utterance.get("words")
            if isinstance(words, list):
                for word_item in words[:5]:
                    if isinstance(word_item, dict):
                        candidates.extend(
                            [
                                word_item.get("start_time"),
                                word_item.get("end_time"),
                                word_item.get("start"),
                                word_item.get("end"),
                            ]
                        )
            if any(max(0.0, _safe_float(value)) > threshold for value in candidates):
                return 0.001

    return 1.0


def _normalize_volcengine_time_seconds(raw_value: Any, time_scale: float) -> float:
    value = max(0.0, _safe_float(raw_value))
    if time_scale > 0:
        value *= time_scale
    return max(0.0, value)


def _extract_volcengine_result_dict(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    if not isinstance(result, dict):
        result = {}
    return result


def _extract_volcengine_words(
    payload: dict[str, Any], total_duration: float
) -> list[dict[str, Any]]:
    result = _extract_volcengine_result_dict(payload)
    time_scale = _resolve_volcengine_time_scale(result, total_duration)

    words: list[dict[str, Any]] = []
    utterances = result.get("utterances")
    if isinstance(utterances, list):
        for utterance_index, utterance in enumerate(utterances):
            if not isinstance(utterance, dict):
                continue
            utterance_start = _normalize_volcengine_time_seconds(
                utterance.get("start_time") or utterance.get("start"),
                time_scale,
            )
            utterance_end = _normalize_volcengine_time_seconds(
                utterance.get("end_time") or utterance.get("end"),
                time_scale,
            )
            utterance_words = utterance.get("words")
            if isinstance(utterance_words, list):
                for word_item in utterance_words:
                    if not isinstance(word_item, dict):
                        continue
                    token = str(
                        word_item.get("text")
                        or word_item.get("word")
                        or word_item.get("text_piece")
                        or ""
                    ).strip()
                    if not token:
                        continue
                    start = _normalize_volcengine_time_seconds(
                        word_item.get("start_time") or word_item.get("start"),
                        time_scale,
                    )
                    end = _normalize_volcengine_time_seconds(
                        word_item.get("end_time") or word_item.get("end"),
                        time_scale,
                    )
                    if end <= start:
                        end = max(start + 0.01, utterance_end)
                    words.append(
                        {
                            "word": token,
                            "start": start,
                            "end": end,
                            "utterance_index": utterance_index,
                        }
                    )
                continue
            token = str(utterance.get("text") or "").strip()
            if token:
                end = utterance_end if utterance_end > utterance_start else utterance_start + 0.01
                words.append(
                    {
                        "word": token,
                        "start": utterance_start,
                        "end": end,
                        "utterance_index": utterance_index,
                    }
                )

    if not words:
        raw_words = result.get("words")
        if isinstance(raw_words, list):
            for index, word_item in enumerate(raw_words):
                if not isinstance(word_item, dict):
                    continue
                token = str(word_item.get("text") or word_item.get("word") or "").strip()
                if not token:
                    continue
                start = _normalize_volcengine_time_seconds(
                    word_item.get("start_time") or word_item.get("start"),
                    time_scale,
                )
                end = _normalize_volcengine_time_seconds(
                    word_item.get("end_time") or word_item.get("end"),
                    time_scale,
                )
                if end <= start:
                    end = start + 0.01
                words.append(
                    {
                        "word": token,
                        "start": start,
                        "end": end,
                        "utterance_index": index,
                    }
                )

    words.sort(key=lambda item: (_safe_float(item.get("start")), _safe_float(item.get("end"))))
    return words


def _summarize_volcengine_result(payload: dict[str, Any]) -> str:
    result = _extract_volcengine_result_dict(payload)
    utterances = result.get("utterances")
    words = result.get("words")
    text = str(result.get("text") or "").strip()
    additions = result.get("additions")
    return (
        f"result_keys={sorted(result.keys())} "
        f"utterances={len(utterances) if isinstance(utterances, list) else 0} "
        f"words={len(words) if isinstance(words, list) else 0} "
        f"text_len={len(text)} "
        f"additions_keys={sorted(additions.keys()) if isinstance(additions, dict) else []}"
    )


def _truncate_volcengine_error_text(value: str, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:300]} ... {text[-200:]}"


def _extract_volcengine_status_code(
    response: httpx.Response, payload: dict[str, Any]
) -> int | None:
    candidates: list[Any] = [
        response.headers.get("X-Api-Status-Code"),
        response.headers.get("x-api-status-code"),
    ]
    header_payload = payload.get("header")
    if isinstance(header_payload, dict):
        candidates.append(header_payload.get("code"))
    candidates.append(payload.get("code"))

    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if not text:
            continue
        try:
            return int(text)
        except ValueError:
            continue
    return None


def _extract_volcengine_status_message(response: httpx.Response, payload: dict[str, Any]) -> str:
    candidates: list[Any] = [
        response.headers.get("X-Api-Message"),
        response.headers.get("x-api-message"),
    ]
    header_payload = payload.get("header")
    if isinstance(header_payload, dict):
        candidates.extend(
            [
                header_payload.get("message"),
                header_payload.get("msg"),
                header_payload.get("error"),
            ]
        )
    candidates.extend(
        [
            payload.get("message"),
            payload.get("msg"),
            payload.get("error"),
            payload.get("error_msg"),
        ]
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _extract_volcengine_task_request_id(
    response: httpx.Response,
    payload: dict[str, Any],
    *,
    fallback: str,
) -> str:
    candidates: list[Any] = [
        response.headers.get("X-Api-Request-Id"),
        response.headers.get("x-api-request-id"),
        payload.get("request_id"),
        payload.get("task_id"),
    ]
    header_payload = payload.get("header")
    if isinstance(header_payload, dict):
        candidates.extend(
            [
                header_payload.get("reqid"),
                header_payload.get("request_id"),
                header_payload.get("task_id"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return str(fallback).strip()


async def _transcribe_audio_words_volcengine(
    audio_path: Path,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    *,
    resource_id_override: str | None = None,
) -> list[dict[str, Any]]:
    if not audio_path.exists():
        logger.warning("[AudioSplit] 音频文件不存在，跳过转写: %s", audio_path)
        return []

    async def _emit_progress(
        *,
        phase: str,
        current_seconds: float,
        total_seconds: float,
        utterance_index: int | None = None,
    ) -> None:
        if on_progress is None:
            return
        total = max(0.0, float(total_seconds or 0.0))
        current = max(0.0, float(current_seconds or 0.0))
        progress = 0.0
        if total > 0:
            progress = max(0.0, min(1.0, current / total))
        payload: dict[str, Any] = {
            "phase": phase,
            "current_seconds": current,
            "total_seconds": total,
            "progress": progress,
        }
        if utterance_index is not None:
            payload["utterance_index"] = int(utterance_index)
        try:
            await on_progress(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AudioSplit] transcribe progress callback failed: %s", exc)

    total_duration = await probe_audio_duration(audio_path)
    await _emit_progress(phase="start", current_seconds=0.0, total_seconds=total_duration)

    app_key = str(settings.speech_volcengine_app_key or "").strip()
    access_key = str(settings.speech_volcengine_access_key or "").strip()
    resource_id = (
        str(
            resource_id_override
            or settings.speech_volcengine_resource_id
            or VOLCENGINE_ASR_DEFAULT_RESOURCE_ID
        ).strip()
        or VOLCENGINE_ASR_DEFAULT_RESOURCE_ID
    )
    language = str(settings.speech_volcengine_language or "").strip()
    if not app_key:
        raise StageRuntimeError("火山语音识别未配置 app_key。")
    if not access_key:
        raise StageRuntimeError("火山语音识别未配置 access_key。")
    if not resource_id:
        raise StageRuntimeError("火山语音识别未配置 resource_id。")

    stat_info = audio_path.stat()
    if stat_info.st_size > VOLCENGINE_ASR_MAX_FILE_SIZE_BYTES:
        raise StageRuntimeError(
            f"火山语音识别文件过大（{stat_info.st_size} 字节），超过 100MB 限制。"
        )
    audio_bytes = audio_path.read_bytes()

    submit_request_id = uuid4().hex
    submit_headers = {
        "X-Api-App-Key": app_key,
        "X-Api-Access-Key": access_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": submit_request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }
    submit_payload = {
        "user": {"uid": "localvideo-asr"},
        "audio": {
            "format": (audio_path.suffix or ".wav").lstrip(".").lower() or "wav",
            "data": base64.b64encode(audio_bytes).decode("ascii"),
        },
        "request": {"model_name": "bigmodel"},
    }
    if language:
        submit_payload["audio"]["language"] = language

    await _emit_progress(
        phase="transcribing",
        current_seconds=0.0,
        total_seconds=total_duration,
    )
    started_at = time.perf_counter()
    response_payload: dict[str, Any] = {}
    extracted_words: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=300.0, trust_env=False) as client:
            submit_response = await client.post(
                VOLCENGINE_ASR_SUBMIT_ENDPOINT,
                headers=submit_headers,
                json=submit_payload,
            )
            submit_response.raise_for_status()
            try:
                raw_submit_payload = submit_response.json()
            except Exception:
                raw_submit_payload = {}
            submit_payload_json = raw_submit_payload if isinstance(raw_submit_payload, dict) else {}
            submit_status_code = _extract_volcengine_status_code(
                submit_response, submit_payload_json
            )
            if submit_status_code not in (None, 0, VOLCENGINE_ASR_SUCCESS_STATUS_CODE):
                submit_message = _extract_volcengine_status_message(
                    submit_response, submit_payload_json
                )
                raise StageRuntimeError(
                    "火山语音识别任务提交失败 "
                    f"(code={submit_status_code}): {submit_message or 'unknown'}"
                )

            query_request_id = _extract_volcengine_task_request_id(
                submit_response,
                submit_payload_json,
                fallback=submit_request_id,
            )
            query_headers = {
                "X-Api-App-Key": app_key,
                "X-Api-Access-Key": access_key,
                "X-Api-Resource-Id": resource_id,
                "X-Api-Request-Id": query_request_id,
                "X-Api-Sequence": "-1",
                "Content-Type": "application/json",
            }
            deadline = time.monotonic() + VOLCENGINE_ASR_QUERY_TIMEOUT_SECONDS
            while True:
                query_response = await client.post(
                    VOLCENGINE_ASR_QUERY_ENDPOINT,
                    headers=query_headers,
                    json={},
                )
                query_response.raise_for_status()
                try:
                    raw_query_payload = query_response.json()
                except Exception as exc:
                    raise StageRuntimeError("火山语音识别响应不是合法 JSON。") from exc
                if not isinstance(raw_query_payload, dict):
                    raise StageRuntimeError("火山语音识别响应格式异常（非字典）。")
                response_payload = raw_query_payload
                status_code = _extract_volcengine_status_code(query_response, response_payload)
                if status_code in VOLCENGINE_ASR_PENDING_STATUS_CODES:
                    if time.monotonic() >= deadline:
                        raise StageRuntimeError(
                            f"火山语音识别超时（>{int(VOLCENGINE_ASR_QUERY_TIMEOUT_SECONDS)}s）。"
                        )
                    elapsed_seconds = max(0.0, time.perf_counter() - started_at)
                    heartbeat = min(
                        total_duration if total_duration > 0 else elapsed_seconds,
                        elapsed_seconds,
                    )
                    await _emit_progress(
                        phase="transcribing",
                        current_seconds=heartbeat,
                        total_seconds=total_duration,
                    )
                    await asyncio.sleep(VOLCENGINE_ASR_QUERY_POLL_SECONDS)
                    continue
                if status_code in (None, 0, VOLCENGINE_ASR_SUCCESS_STATUS_CODE):
                    extracted_words = _extract_volcengine_words(response_payload, total_duration)
                    if extracted_words:
                        break
                    if time.monotonic() >= deadline:
                        logger.warning(
                            "[AudioSplit] volcengine-asr completed without usable timestamps: "
                            "audio=%s model=%s status=%s summary=%s",
                            audio_path,
                            resource_id,
                            status_code,
                            _summarize_volcengine_result(response_payload),
                        )
                        break
                    logger.info(
                        "[AudioSplit] volcengine-asr completed but result has no usable timestamps yet; retrying: "
                        "audio=%s model=%s status=%s summary=%s",
                        audio_path,
                        resource_id,
                        status_code,
                        _summarize_volcengine_result(response_payload),
                    )
                    await asyncio.sleep(VOLCENGINE_ASR_QUERY_POLL_SECONDS)
                    continue
                if status_code == VOLCENGINE_ASR_SILENCE_STATUS_CODE:
                    logger.info(
                        "[AudioSplit] volcengine-asr 返回静音结果: audio=%s model=%s",
                        audio_path,
                        resource_id,
                    )
                    await _emit_progress(
                        phase="done",
                        current_seconds=total_duration,
                        total_seconds=total_duration,
                    )
                    return []

                message = _extract_volcengine_status_message(query_response, response_payload)
                raise StageRuntimeError(
                    f"火山语音识别失败 code={status_code}: {message or 'unknown'}"
                )
    except httpx.HTTPStatusError as exc:
        body = _truncate_volcengine_error_text(exc.response.text or "")
        raise StageRuntimeError(
            f"火山语音识别请求失败（HTTP {exc.response.status_code}）: {body or '<empty>'}"
        ) from exc
    except Exception as exc:
        raise StageRuntimeError(f"火山语音识别请求异常: {exc}") from exc
    elapsed = time.perf_counter() - started_at
    logger.info(
        "[AudioSplit] volcengine-asr 转写结束: elapsed=%.2fs audio=%s model=%s",
        elapsed,
        audio_path,
        resource_id,
    )

    words = extracted_words or _extract_volcengine_words(response_payload, total_duration)
    normalized_words = _extract_word_items({"words": words})
    if normalized_words:
        words = normalized_words
    if not words and response_payload:
        logger.warning(
            "[AudioSplit] volcengine-asr 未提取到词级时间轴: audio=%s model=%s summary=%s",
            audio_path,
            resource_id,
            _summarize_volcengine_result(response_payload),
        )
    if words:
        last_end = _safe_float(words[-1].get("end"))
        await _emit_progress(
            phase="done",
            current_seconds=last_end if last_end > 0 else total_duration,
            total_seconds=total_duration if total_duration > 0 else last_end,
        )
    else:
        await _emit_progress(
            phase="done",
            current_seconds=total_duration,
            total_seconds=total_duration,
        )
    return words


async def transcribe_audio_words(
    audio_path: Path,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    *,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    provider, resolved_model = _resolve_speech_runtime(provider=provider_name, model=model_name)
    logger.info(
        "[AudioSplit] 语音识别服务: provider=%s model=%s audio=%s",
        provider,
        resolved_model,
        audio_path,
    )
    if provider == SPEECH_RECOGNITION_PROVIDER_VOLCENGINE:
        return await _transcribe_audio_words_volcengine(
            audio_path,
            on_progress=on_progress,
            resource_id_override=resolved_model,
        )
    return await _transcribe_audio_words_faster_whisper(
        audio_path,
        on_progress=on_progress,
        model_name_override=resolved_model,
    )


def _resolve_split_mode(split_mode: str | None) -> str:
    normalized = str(split_mode or AUDIO_SPLIT_MODE_BASIC).strip().lower()
    if normalized in SUPPORTED_AUDIO_SPLIT_MODES:
        return normalized
    return AUDIO_SPLIT_MODE_BASIC


def _build_sequence_alignment_map(
    source_text: str,
    target_text: str,
) -> tuple[list[int | None], float]:
    if not source_text or not target_text:
        return ([], 0.0)

    matcher = difflib.SequenceMatcher(
        isjunk=None,
        a=source_text,
        b=target_text,
        autojunk=False,
    )
    mapping: list[int | None] = [None] * len(source_text)

    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        source_len = a1 - a0
        target_len = b1 - b0
        if source_len <= 0:
            continue

        if tag == "equal":
            for offset in range(source_len):
                mapping[a0 + offset] = b0 + offset
            continue

        if tag == "replace" and target_len > 0:
            if source_len == 1:
                mapping[a0] = b0 + (target_len // 2)
            else:
                for offset in range(source_len):
                    ratio = offset / (source_len - 1)
                    mapped_index = b0 + int(round(ratio * (target_len - 1)))
                    mapping[a0 + offset] = mapped_index

    return (mapping, matcher.ratio())


def _nearest_mapped_index(
    mapping: list[int | None],
    start: int,
    end: int,
    *,
    direction: str,
) -> int | None:
    if not mapping:
        return None
    max_index = len(mapping)
    safe_start = max(0, min(start, max_index))
    safe_end = max(0, min(end, max_index))
    if direction == "forward":
        for idx in range(safe_start, safe_end):
            mapped = mapping[idx]
            if isinstance(mapped, int):
                return mapped
        return None

    for idx in range(safe_end - 1, safe_start - 1, -1):
        mapped = mapping[idx]
        if isinstance(mapped, int):
            return mapped
    return None


def _resolve_shot_match_span(
    mapping: list[int | None],
    start: int,
    end: int,
) -> tuple[int, int] | None:
    if not mapping:
        return None

    first = _nearest_mapped_index(mapping, start, end, direction="forward")
    last = _nearest_mapped_index(mapping, start, end, direction="backward")

    if first is None:
        first = _nearest_mapped_index(mapping, end, len(mapping), direction="forward")
    if first is None and start > 0:
        first = _nearest_mapped_index(mapping, 0, start, direction="backward")

    if last is None and start > 0:
        last = _nearest_mapped_index(mapping, 0, start, direction="backward")
    if last is None:
        last = _nearest_mapped_index(mapping, end, len(mapping), direction="forward")

    if first is None and last is None:
        return None
    if first is None:
        first = last
    if last is None:
        last = first
    if first is None or last is None:
        return None

    if last < first:
        last = first
    return (first, last)


def _build_aligned_shot_bounds(
    words: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    total_duration: float,
) -> list[dict[str, Any]] | None:
    if not words or not shots:
        logger.warning(
            "[AudioSplit] 对齐切分前置条件不足: words=%d shots=%d",
            len(words),
            len(shots),
        )
        return None

    normalized_stream_parts: list[str] = []
    char_to_word_index: list[int] = []

    for word_index, item in enumerate(words):
        normalized = str(item.get("normalized") or "")
        if not normalized:
            continue
        normalized_stream_parts.append(normalized)
        char_to_word_index.extend([word_index] * len(normalized))

    normalized_stream = "".join(normalized_stream_parts)
    if not normalized_stream or not char_to_word_index:
        logger.warning("[AudioSplit] 对齐失败: 识别流为空")
        return None
    logger.info(
        "[AudioSplit] 对齐开始: shots=%d words=%d stream_chars=%d total_duration=%.3fs",
        len(shots),
        len(words),
        len(normalized_stream),
        max(0.0, float(total_duration or 0.0)),
    )

    script_parts: list[str] = []
    script_shot_ranges: list[tuple[int, int]] = []
    script_cursor = 0

    for shot in shots:
        normalized_shot = _normalize_match_text(str(shot.get("voice_content") or ""))
        start = script_cursor
        script_cursor += len(normalized_shot)
        script_parts.append(normalized_shot)
        script_shot_ranges.append((start, script_cursor))

    normalized_script = "".join(script_parts)
    if not normalized_script:
        logger.warning("[AudioSplit] 对齐失败: 文案规范化后为空")
        return None

    char_mapping, align_ratio = _build_sequence_alignment_map(normalized_script, normalized_stream)
    if not char_mapping:
        logger.warning("[AudioSplit] 对齐失败: 序列对齐结果为空")
        return None
    covered = sum(1 for item in char_mapping if isinstance(item, int))
    coverage = covered / max(1, len(char_mapping))
    logger.info(
        "[AudioSplit] 序列对齐: script_chars=%d stream_chars=%d ratio=%.4f coverage=%.4f",
        len(normalized_script),
        len(normalized_stream),
        align_ratio,
        coverage,
    )
    if coverage < ALIGNMENT_MIN_COVERAGE:
        logger.warning(
            "[AudioSplit] 对齐覆盖率过低: coverage=%.4f threshold=%.2f",
            coverage,
            ALIGNMENT_MIN_COVERAGE,
        )
        return None

    bounds: list[dict[str, Any]] = []
    previous_end = 0.0
    previous_end_word = -1

    for shot_index, shot in enumerate(shots):
        voice_content = str(shot.get("voice_content") or "")
        normalized_shot = script_parts[shot_index]
        range_start, range_end = script_shot_ranges[shot_index]
        logger.info(
            "[AudioSplit] 对齐 shot[%03d] 原文长度=%d 规范化长度=%d 文本=%s",
            shot_index,
            len(voice_content),
            len(normalized_shot),
            _preview_text(voice_content),
        )
        if not normalized_shot:
            shot_start = previous_end
            shot_end = total_duration if shot_index == len(shots) - 1 else shot_start
            bounds.append(
                {
                    "shot_index": shot_index,
                    "start": shot_start,
                    "end": max(shot_start, shot_end),
                    "start_word": None,
                    "end_word": None,
                }
            )
            previous_end = max(shot_start, shot_end)
            logger.info(
                "[AudioSplit] 对齐 shot[%03d] 跳过（规范化后为空） start=%.3f end=%.3f",
                shot_index,
                max(0.0, float(shot_start)),
                max(shot_start, shot_end),
            )
            continue

        match_span = _resolve_shot_match_span(char_mapping, range_start, range_end)
        if match_span is None:
            logger.warning(
                "[AudioSplit] 对齐失败 shot[%03d]: 序列映射区间为空 script_range=%d-%d",
                shot_index,
                range_start,
                range_end,
            )
            return None
        match_start, match_end = match_span
        match_start = max(0, min(match_start, len(char_to_word_index) - 1))
        match_end = max(match_start, min(match_end, len(char_to_word_index) - 1))

        start_word = char_to_word_index[match_start]
        end_word = char_to_word_index[match_end]
        if start_word <= previous_end_word:
            start_word = min(len(words) - 1, previous_end_word + 1)
        if end_word < start_word:
            end_word = start_word

        start_time = max(0.0, _safe_float(words[start_word].get("start"), previous_end))
        end_time = max(
            start_time + 0.01, _safe_float(words[end_word].get("end"), start_time + 0.01)
        )

        if shot_index == 0:
            shot_start = 0.0
        else:
            # Weighted boundary (7/3) toward current utterance start time
            # to reduce hearing previous utterance tail at next utterance start.
            boundary = (
                previous_end * BOUNDARY_BLEND_PREVIOUS_END
                + start_time * BOUNDARY_BLEND_CURRENT_START
            )
            if bounds:
                prev_bound = bounds[-1]
                prev_start = max(0.0, _safe_float(prev_bound.get("start")))
                boundary = max(prev_start + 0.01, boundary)
                boundary = min(total_duration, boundary)
                prev_bound["end"] = boundary
            shot_start = boundary

        if shot_index == len(shots) - 1:
            shot_end = max(shot_start + 0.01, total_duration)
        else:
            shot_end = max(shot_start + 0.01, min(total_duration, end_time))

        bounds.append(
            {
                "shot_index": shot_index,
                "start": shot_start,
                "end": shot_end,
                "start_word": start_word,
                "end_word": end_word,
                "match_start_time": start_time,
                "match_end_time": end_time,
            }
        )
        logger.info(
            "[AudioSplit] 对齐 shot[%03d] 命中: char=%d-%d word=%d-%d time=%.3f->%.3f split=%.3f->%.3f",
            shot_index,
            match_start,
            match_end,
            start_word,
            end_word,
            start_time,
            end_time,
            shot_start,
            shot_end,
        )

        previous_end = shot_end
        previous_end_word = end_word

    if bounds:
        bounds[-1]["end"] = max(bounds[-1].get("start", 0.0) + 0.01, total_duration)
        logger.info(
            "[AudioSplit] 对齐完成: shot_count=%d last_end=%.3f",
            len(bounds),
            _safe_float(bounds[-1].get("end")),
        )

    return bounds


def _format_srt_time(seconds: float) -> str:
    value = max(0.0, float(seconds or 0.0))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    secs = int(value % 60)
    millis = int(round((value - int(value)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    if secs >= 60:
        minutes += 1
        secs -= 60
    if minutes >= 60:
        hours += 1
        minutes -= 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _join_word_text(current: str, token: str) -> str:
    if not current:
        return token
    if re.search(r"[\u4e00-\u9fff]$", current) or re.search(r"^[\u4e00-\u9fff]", token):
        return f"{current}{token}"
    return f"{current} {token}"


def _build_srt_from_aligned_words(
    *,
    words: list[dict[str, Any]],
    shot_start: float,
    shot_end: float,
    start_word: int,
    end_word: int,
    fallback_text: str,
) -> tuple[str, int]:
    selected = [
        item
        for idx, item in enumerate(words)
        if start_word <= idx <= end_word and isinstance(item, dict)
    ]

    if not selected:
        duration = max(0.01, shot_end - shot_start)
        content, lines = generate_srt_content(fallback_text, duration)
        return content, lines

    entries: list[str] = []
    line_count = 0
    chunk_text = ""
    chunk_start: float | None = None
    chunk_end: float | None = None
    last_word_end: float | None = None
    chunk_index = 1

    def flush_chunk() -> None:
        nonlocal chunk_text, chunk_start, chunk_end, chunk_index, line_count
        if not chunk_text or chunk_start is None or chunk_end is None:
            chunk_text = ""
            chunk_start = None
            chunk_end = None
            return

        relative_start = max(0.0, chunk_start - shot_start)
        relative_end = max(relative_start + 0.01, chunk_end - shot_start)
        wrapped = chunk_text.strip()
        if not wrapped:
            chunk_text = ""
            chunk_start = None
            chunk_end = None
            return

        entries.append(str(chunk_index))
        entries.append(f"{_format_srt_time(relative_start)} --> {_format_srt_time(relative_end)}")
        entries.append(wrapped)
        entries.append("")
        line_count += wrapped.count("\n") + 1
        chunk_index += 1

        chunk_text = ""
        chunk_start = None
        chunk_end = None

    for item in selected:
        token = str(item.get("word") or "").strip()
        if not token:
            continue

        token_start = _safe_float(item.get("start"), shot_start)
        token_end = max(token_start + 0.01, _safe_float(item.get("end"), token_start + 0.01))

        if chunk_start is None:
            chunk_start = token_start
            chunk_text = token
            chunk_end = token_end
            last_word_end = token_end
            continue

        gap_break = (
            last_word_end is not None and token_start - last_word_end >= SRT_MAX_WORD_GAP_SECONDS
        )
        candidate = _join_word_text(chunk_text, token)
        candidate_len = len(_normalize_match_text(candidate))
        punctuation_break = bool(SRT_SENTENCE_BREAK_PATTERN.search(token))

        if gap_break or candidate_len >= SRT_MAX_CHARS_PER_LINE:
            flush_chunk()
            chunk_start = token_start
            chunk_text = token
            chunk_end = token_end
            last_word_end = token_end
            continue

        chunk_text = candidate
        chunk_end = token_end
        last_word_end = token_end

        if punctuation_break:
            flush_chunk()
            last_word_end = token_end

    flush_chunk()

    if not entries:
        duration = max(0.01, shot_end - shot_start)
        content, lines = generate_srt_content(fallback_text, duration)
        return content, lines

    return "\n".join(entries), max(1, line_count)


async def split_full_audio_by_shots(
    full_audio_path: Path,
    shots: list[dict[str, Any]],
    output_dir: Path,
    total_duration: float | None = None,
    subtitle_dir: Path | None = None,
    split_mode: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if not full_audio_path.exists():
        raise FileNotFoundError(f"Full audio file not found: {full_audio_path}")
    logger.info(
        "[AudioSplit] 切分开始: audio=%s shots=%d split_mode=%s requested_total_duration=%.3f",
        full_audio_path,
        len(shots),
        split_mode,
        max(0.0, float(total_duration or 0.0)),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    if subtitle_dir is not None:
        subtitle_dir.mkdir(parents=True, exist_ok=True)

    resolved_total_duration = float(total_duration or 0.0)
    if resolved_total_duration <= 0:
        logger.info("[AudioSplit] 未提供总时长，调用 ffprobe 探测")
        resolved_total_duration = await probe_audio_duration(full_audio_path)
    if resolved_total_duration <= 0:
        raise StageValidationError("无法获取整段音频时长，无法切分")
    logger.info("[AudioSplit] 总时长=%.3f 秒", resolved_total_duration)

    aligned_words: list[dict[str, Any]] = []
    aligned_bounds: list[dict[str, Any]] | None = None
    resolved_split_mode = _resolve_split_mode(split_mode)
    split_method = "basic_proportional"

    if resolved_split_mode == AUDIO_SPLIT_MODE_FASTER_WHISPER:
        speech_provider, speech_model = _resolve_speech_runtime()
        aligned_words = await transcribe_audio_words(
            full_audio_path,
            provider_name=speech_provider,
            model_name=speech_model,
        )
        if not aligned_words:
            raise StageRuntimeError("语音识别未返回有效词级时间戳，无法切分音频。")
        aligned_bounds = _build_aligned_shot_bounds(aligned_words, shots, resolved_total_duration)
        if not aligned_bounds:
            raise StageRuntimeError(
                "语音识别文案与转写对齐失败，已禁止回退到按字数比例切分。"
                "请检查文案与语音是否一致，或切换到基础版切分。"
            )
        split_method = f"{speech_provider}_alignment"
        logger.info(
            "[AudioSplit] 切分策略: 语音识别对齐 provider=%s model=%s shots=%d",
            speech_provider,
            speech_model,
            len(aligned_bounds),
        )
    else:
        logger.info("[AudioSplit] 切分策略: basic 按比例切分")

    proportional_plan: list[tuple[float, float]] = []
    if not aligned_bounds:
        proportional_plan = _build_shot_duration_plan(resolved_total_duration, shots)
        for shot_index, (plan_start, plan_duration) in enumerate(proportional_plan):
            logger.info(
                "[AudioSplit] 计划 shot[%03d] start=%.3f duration=%.3f",
                shot_index,
                plan_start,
                plan_duration,
            )

    suffix = full_audio_path.suffix or ".wav"
    timestamp = int(time.time())

    audio_assets: list[dict[str, Any]] = []
    subtitle_assets: list[dict[str, Any]] = []

    for shot_index, shot in enumerate(shots):
        if aligned_bounds:
            bound = aligned_bounds[shot_index]
            clip_start = max(0.0, float(bound.get("start") or 0.0))
            clip_end = max(clip_start + 0.01, float(bound.get("end") or (clip_start + 0.01)))
            clip_duration = max(0.01, clip_end - clip_start)
            logger.info(
                "[AudioSplit] 执行 shot[%03d] 对齐切分 start=%.3f end=%.3f duration=%.3f",
                shot_index,
                clip_start,
                clip_end,
                clip_duration,
            )
        else:
            plan_start, plan_duration = proportional_plan[shot_index]
            clip_start = max(0.0, float(plan_start or 0.0))
            clip_duration = max(0.01, float(plan_duration or 0.0))
            clip_end = clip_start + clip_duration
            logger.info(
                "[AudioSplit] 执行 shot[%03d] 比例切分 start=%.3f end=%.3f duration=%.3f",
                shot_index,
                clip_start,
                clip_end,
                clip_duration,
            )

        output_path = output_dir / f"shot_{shot_index:03d}{suffix}"

        for existing in output_dir.glob(f"shot_{shot_index:03d}.*"):
            if existing != output_path and existing.is_file():
                existing.unlink(missing_ok=True)

        await _slice_audio_clip(full_audio_path, output_path, clip_start, clip_duration)
        actual_duration = await probe_audio_duration(output_path)
        resolved_duration = actual_duration if actual_duration > 0 else float(clip_duration)
        logger.info(
            "[AudioSplit] 完成 shot[%03d] 输出=%s duration(plan=%.3f actual=%.3f)",
            shot_index,
            output_path,
            clip_duration,
            resolved_duration,
        )
        audio_assets.append(
            {
                "shot_index": shot_index,
                "file_path": str(output_path),
                "duration": resolved_duration,
                "voice_content": str(shot.get("voice_content") or ""),
                "split_start": clip_start,
                "split_end": clip_start + resolved_duration,
                "updated_at": timestamp,
            }
        )

        if subtitle_dir is not None:
            subtitle_path = subtitle_dir / f"shot_{shot_index:03d}.srt"
            voice_content = str(shot.get("voice_content") or "")

            # 字幕文本始终以原始文案为准；
            # 语音识别仅用于确定音频切分边界，不直接驱动字幕内容。
            srt_content, line_count = generate_srt_content(voice_content, resolved_duration)

            subtitle_path.write_text(srt_content, encoding="utf-8")
            logger.info(
                "[AudioSplit] 字幕 shot[%03d] 输出=%s lines=%d mode=%s",
                shot_index,
                subtitle_path,
                line_count,
                "original_script",
            )
            subtitle_assets.append(
                {
                    "shot_index": shot_index,
                    "file_path": str(subtitle_path),
                    "line_count": line_count,
                    "updated_at": timestamp,
                }
            )

    logger.info(
        "[AudioSplit] 切分结束: audio_assets=%d subtitle_assets=%d split_method=%s",
        len(audio_assets),
        len(subtitle_assets),
        split_method,
    )
    return audio_assets, subtitle_assets, split_method


def cleanup_stale_shot_audio_files(output_dir: Path, valid_indices: set[int]) -> None:
    if not output_dir.exists() or not output_dir.is_dir():
        return

    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        match = SHOT_FILE_PATTERN.match(file_path.name)
        if not match:
            continue
        shot_index = int(match.group(1))
        if shot_index not in valid_indices:
            file_path.unlink(missing_ok=True)


def cleanup_stale_shot_subtitle_files(output_dir: Path, valid_indices: set[int]) -> None:
    if not output_dir.exists() or not output_dir.is_dir():
        return

    for file_path in output_dir.iterdir():
        if not file_path.is_file() or file_path.suffix.lower() != ".srt":
            continue
        match = SHOT_FILE_PATTERN.match(file_path.name)
        if not match:
            continue
        shot_index = int(match.group(1))
        if shot_index not in valid_indices:
            file_path.unlink(missing_ok=True)
