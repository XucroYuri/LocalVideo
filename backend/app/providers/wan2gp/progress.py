from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from enum import IntEnum

STATUS_PREPARING = "准备中..."
STATUS_MODEL_DOWNLOADING = "模型下载中..."
STATUS_MODEL_LOADING = "模型加载中..."
STATUS_GENERATING = "生成中..."


class Wan2GPPhase(IntEnum):
    PREPARING = 10
    MODEL_DOWNLOADING = 20
    MODEL_LOADING = 30
    GENERATING = 40
    UNKNOWN = 99


_LOADING_KEYWORDS = (
    "loading model",
    "model loaded",
    "download complete",
    "moving file to",
    "loading text encoder",
    "loading vae",
    "loading transformer",
    "memory management for the gpu poor",
    "pinning data",
)

_DOWNLOAD_KEYWORDS = (
    "downloading",
    "download ",
    "hf_hub_download",
    "snapshot_download",
)


def extract_percent_from_text(text: str | None, clamp_max: int = 100) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)%", text)
    if not match:
        return None
    try:
        value = int(float(match.group(1)))
    except Exception:
        return None
    return max(0, min(clamp_max, value))


def _phase_from_message(message: str | None) -> Wan2GPPhase:
    text = (message or "").strip()
    if not text:
        return Wan2GPPhase.UNKNOWN
    if text.startswith("准备中"):
        return Wan2GPPhase.PREPARING
    if text.startswith("模型下载中"):
        return Wan2GPPhase.MODEL_DOWNLOADING
    if text.startswith("模型加载中") or text.startswith("模型已下载，加载中"):
        return Wan2GPPhase.MODEL_LOADING
    if text.startswith("生成中") or text.startswith("执行中"):
        return Wan2GPPhase.GENERATING
    return Wan2GPPhase.UNKNOWN


def normalize_status_message(message: str | None) -> str | None:
    raw = (message or "").strip()
    if not raw:
        return None
    if raw.startswith("准备中"):
        return STATUS_PREPARING
    if raw.startswith("模型已下载，加载中"):
        return STATUS_MODEL_LOADING
    if raw.startswith("模型加载中"):
        return STATUS_MODEL_LOADING
    if raw.startswith("模型下载中"):
        pct = extract_percent_from_text(raw)
        suffix = raw[len("模型下载中") :].strip()
        if suffix.startswith("..."):
            suffix = suffix[3:].strip()
        if suffix.startswith(":") or suffix.startswith("："):
            suffix = suffix[1:].strip()
        suffix = re.sub(r"\s*[（(]?\d+(?:\.\d+)?%\s*[)）]?\s*$", "", suffix).strip()
        if suffix and pct is not None:
            return f"{STATUS_MODEL_DOWNLOADING} {suffix} ({pct}%)"
        if suffix:
            return f"{STATUS_MODEL_DOWNLOADING} {suffix}"
        if pct is not None:
            return f"{STATUS_MODEL_DOWNLOADING} ({pct}%)"
        return STATUS_MODEL_DOWNLOADING
    if raw.startswith("生成中"):
        suffix = raw[len("生成中") :].strip()
        if suffix.startswith("..."):
            suffix = suffix[3:].strip()
        if not suffix:
            return STATUS_GENERATING
        if suffix.startswith("（") or suffix.startswith("("):
            return f"{STATUS_GENERATING}{suffix}"
        return f"{STATUS_GENERATING} {suffix}"
    if raw.startswith("执行中"):
        suffix = raw[len("执行中") :].strip()
        if suffix.startswith("..."):
            suffix = suffix[3:].strip()
        if not suffix:
            return STATUS_GENERATING
        if suffix.startswith("（") or suffix.startswith("("):
            return f"{STATUS_GENERATING}{suffix}"
        return f"{STATUS_GENERATING} {suffix}"
    return raw


def should_advance_status(current: str | None, candidate: str | None) -> bool:
    current_norm = normalize_status_message(current)
    candidate_norm = normalize_status_message(candidate)
    if not candidate_norm:
        return False
    if not current_norm:
        return True
    current_phase = _phase_from_message(current_norm)
    candidate_phase = _phase_from_message(candidate_norm)
    if (
        current_phase == Wan2GPPhase.MODEL_LOADING
        and candidate_phase == Wan2GPPhase.MODEL_DOWNLOADING
    ):
        # Some runtimes log "loading model" before the download progress line appears.
        # Allow switching back to download status so UI can show real download progress.
        return True
    if current_phase == Wan2GPPhase.GENERATING and candidate_phase == Wan2GPPhase.MODEL_DOWNLOADING:
        # Runtime logs can occasionally emit generation-like hints before model downloads finish.
        # If download progress lines appear, prefer download status for accurate UI feedback.
        return True
    return candidate_phase >= current_phase


def infer_runtime_status_message(line: str) -> str | None:
    text = (line or "").strip()
    if not text:
        return None
    lower = text.lower()

    sliding_window_match = re.search(r"sliding\s*window\s*(\d+)\s*/\s*(\d+)", text, re.IGNORECASE)
    if sliding_window_match:
        current_window = int(sliding_window_match.group(1))
        total_windows = int(sliding_window_match.group(2))
        if total_windows > 1:
            return f"{STATUS_GENERATING}（滑窗 {current_window}/{total_windows}）"
        return STATUS_GENERATING

    # Wan2GP runtime generation tqdm for Qwen3 TTS, e.g.
    # "Qwen3 TTS: 13%|...| 4/30 [00:12<01:23, 3.20s/s]"
    # These are inference progress lines, not model download lines.
    if re.search(r"qwen3\s*tts\s*:\s*\d+(?:\.\d+)?%\|.*\|\s*\d+\s*/\s*\d+\s*\[", lower):
        return STATUS_GENERATING

    # Generation loop hints from runtime output.
    if "denoising" in lower and re.search(r"\d+\s*s\s*/\s*\d+\s*s", lower):
        return STATUS_GENERATING

    if any(keyword in lower for keyword in _LOADING_KEYWORDS):
        return STATUS_MODEL_LOADING

    percent = extract_percent_from_text(text)
    download_filename: str | None = None
    download_match = re.search(
        r"Downloading\s+['\"](?P<filename>[^'\"]+)['\"]", text, re.IGNORECASE
    )
    if download_match:
        download_filename = download_match.group("filename").strip()
    if any(keyword in lower for keyword in _DOWNLOAD_KEYWORDS) or lower.startswith("download:"):
        if download_filename and percent is not None:
            return f"{STATUS_MODEL_DOWNLOADING} {download_filename} ({percent}%)"
        if download_filename:
            return f"{STATUS_MODEL_DOWNLOADING} {download_filename}"
        if percent is not None:
            return f"{STATUS_MODEL_DOWNLOADING} ({percent}%)"
        return STATUS_MODEL_DOWNLOADING

    # tqdm / size-style download line, e.g. "foo.safetensors: 63%|...| 2.1G/3.5G"
    has_tqdm_hint = bool(re.search(r"\d+(?:\.\d+)?%\|", text)) and "/" in text
    has_size_hint = bool(re.search(r"(kb|mb|gb|tb)\s*/\s*[^)]*(kb|mb|gb|tb)", lower))
    if has_tqdm_hint or has_size_hint:
        if ":" in text:
            candidate = text.split(":", 1)[0].strip()
            if candidate and len(candidate) <= 200:
                download_filename = candidate
        if download_filename and percent is not None:
            return f"{STATUS_MODEL_DOWNLOADING} {download_filename} ({percent}%)"
        if download_filename:
            return f"{STATUS_MODEL_DOWNLOADING} {download_filename}"
        if percent is not None:
            return f"{STATUS_MODEL_DOWNLOADING} ({percent}%)"
        return STATUS_MODEL_DOWNLOADING

    return None


async def emit_bootstrap_status(
    status_callback: Callable[[str], Awaitable[None]] | None,
    model_cached: bool | None,
) -> None:
    if not status_callback:
        return

    messages = [STATUS_PREPARING]
    if model_cached is True:
        messages.append(STATUS_MODEL_LOADING)
    elif model_cached is False:
        messages.append(STATUS_MODEL_DOWNLOADING)

    sent: set[str] = set()
    for message in messages:
        if message in sent:
            continue
        sent.add(message)
        try:
            await status_callback(message)
        except Exception:
            pass
