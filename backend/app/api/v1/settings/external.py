import asyncio
import base64
import json
import math
import re
import shutil
import struct
import tempfile
import time
import wave
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.services.crawl4ai_runtime import validate_crawl4ai_installation
from app.services.faster_whisper_runtime import (
    resolve_faster_whisper_model_name,
    transcribe_with_faster_whisper,
)
from app.services.settings_store import PERSISTABLE_SETTING_KEYS, SettingsStoreService

from ._common import (
    RUNTIME_VALIDATION_STATUS_FAILED,
    RUNTIME_VALIDATION_STATUS_NOT_READY,
    RUNTIME_VALIDATION_STATUS_READY,
    _mask_key,
    _normalize_optional_path,
    logger,
)

router = APIRouter()

VOLCENGINE_ASR_SUBMIT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLCENGINE_ASR_QUERY_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
VOLCENGINE_ASR_SUCCESS_STATUS_CODE = 20000000
VOLCENGINE_ASR_PENDING_STATUS_CODES = {20000001, 20000002}
VOLCENGINE_ASR_SILENCE_STATUS_CODE = 20000003
VOLCENGINE_ASR_QUERY_TIMEOUT_SECONDS = 90.0
VOLCENGINE_ASR_QUERY_POLL_SECONDS = 1.0


class Wan2GPValidateRequest(BaseModel):
    wan2gp_path: str | None = None
    local_model_python_path: str | None = None


class Wan2GPValidateResponse(BaseModel):
    valid: bool
    wan2gp_path: str
    python_path: str
    torch_version: str


class FasterWhisperValidateRequest(BaseModel):
    model: str | None = None


class FasterWhisperValidateResponse(BaseModel):
    valid: bool
    model: str
    device: str
    compute_type: str
    elapsed_ms: int
    utterance_count: int
    word_count: int
    preview_text: str


class VolcengineSpeechValidateRequest(BaseModel):
    app_key: str | None = None
    access_key: str | None = None
    resource_id: str | None = None
    language: str | None = None


class VolcengineSpeechValidateResponse(BaseModel):
    valid: bool
    app_key_masked: str
    resource_id: str
    language: str | None
    elapsed_ms: int
    utterance_count: int
    word_count: int
    preview_text: str


class Crawl4AIValidateRequest(BaseModel):
    pass


class Crawl4AIValidateResponse(BaseModel):
    valid: bool
    command_path: str
    command: str
    output_preview: str


class XHSDownloaderValidateRequest(BaseModel):
    xhs_downloader_path: str | None = None


class XHSDownloaderValidateResponse(BaseModel):
    valid: bool
    xhs_downloader_path: str
    uv_path: str
    entry: str


class TikTokDownloaderValidateRequest(BaseModel):
    tiktok_downloader_path: str | None = None


class TikTokDownloaderValidateResponse(BaseModel):
    valid: bool
    tiktok_downloader_path: str
    uv_path: str
    entry: str


class KSDownloaderValidateRequest(BaseModel):
    ks_downloader_path: str | None = None


class KSDownloaderValidateResponse(BaseModel):
    valid: bool
    ks_downloader_path: str
    uv_path: str
    entry: str


class JinaReaderUsageRequest(BaseModel):
    jina_reader_api_key: str | None = None


class JinaReaderUsageResponse(BaseModel):
    available: bool
    remaining_tokens: float | None = None
    rate_limit_rpm: int | None = None
    raw_preview: str | None = None


class TavilyUsageResponse(BaseModel):
    available: bool
    remaining_credits: float | None = None
    used_credits: float | None = None
    total_credits: float | None = None
    source: str | None = None
    account_used_credits: float | None = None
    account_total_credits: float | None = None
    account_remaining_credits: float | None = None
    key_used_credits: float | None = None
    key_total_credits: float | None = None
    key_remaining_credits: float | None = None
    reset_at: str | None = None
    raw: dict | None = None


def _runtime_component_status(*, ready: bool, success: bool) -> str:
    if not ready:
        return RUNTIME_VALIDATION_STATUS_NOT_READY
    return RUNTIME_VALIDATION_STATUS_READY if success else RUNTIME_VALIDATION_STATUS_FAILED


async def _persist_runtime_validation_status(
    db: AsyncSession,
    *,
    key: str,
    status: str,
) -> None:
    if not hasattr(settings, key):
        return
    setattr(settings, key, status)
    if key not in PERSISTABLE_SETTING_KEYS:
        return
    store = SettingsStoreService(db)
    await store.upsert_many({key: status})


def _resolve_uv_path() -> str:
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path
    raise HTTPException(
        status_code=400,
        detail=(
            "未找到 uv 可执行文件。"
            "请先安装 uv（https://docs.astral.sh/uv/getting-started/installation/），"
            "并确保命令 `uv` 可在 PATH 中访问。"
        ),
    )


def _format_process_output(stdout: bytes, stderr: bytes) -> str:
    combined = []
    if stdout:
        combined.extend(stdout.decode(errors="ignore").splitlines())
    if stderr:
        combined.extend(stderr.decode(errors="ignore").splitlines())
    if not combined:
        return "<no output>"
    tail = combined[-12:]
    return "\n".join(tail)


def _resolve_local_model_python_path(local_model_python_path: str | None) -> Path:
    configured = _normalize_optional_path(local_model_python_path) or _normalize_optional_path(
        settings.local_model_python_path
    )
    if not configured:
        raise HTTPException(status_code=400, detail="缺少共享 Python 路径。")

    python_path = Path(configured).expanduser()
    if not python_path.exists() or not python_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"共享 Python 路径无效（文件不存在）: {python_path}",
        )
    return python_path


async def _fetch_jina_reader_usage(
    jina_reader_api_key: str | None,
) -> tuple[float | None, int | None, str | None]:
    key = (
        str(jina_reader_api_key or settings.jina_reader_api_key or "").strip().strip("\"'").strip()
    )

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    reader_url = "https://r.jina.ai"

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(reader_url, headers=headers)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Jina Reader 连接失败: {exc}",
        )

    if response.status_code >= 400:
        body_preview = (response.text or "").strip()
        if len(body_preview) > 400:
            body_preview = f"{body_preview[:200]} ... {body_preview[-150:]}"
        raise HTTPException(
            status_code=400,
            detail=(
                f"Jina Reader 查询失败（HTTP {response.status_code}）。"
                f"{' 响应：' + body_preview if body_preview else ''}"
            ),
        )

    text = (response.text or "").strip()
    preview = text
    if len(preview) > 280:
        preview = f"{preview[:140]} ... {preview[-100:]}"

    def _as_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            one = value.strip()
            if not one:
                return None
            try:
                return float(one)
            except ValueError:
                return None
        return None

    def _as_int(value: object) -> int | None:
        parsed = _as_float(value)
        if parsed is None:
            return None
        try:
            return int(parsed)
        except (TypeError, ValueError):
            return None

    header_lookup = {str(k).lower(): str(v) for k, v in response.headers.items()}
    rate_limit_rpm = _as_int(
        header_lookup.get("x-ratelimit-limit")
        or header_lookup.get("ratelimit-limit")
        or header_lookup.get("x-rate-limit-limit")
    )
    remaining_tokens = _as_float(
        header_lookup.get("x-usage-remaining-tokens")
        or header_lookup.get("x-remaining-tokens")
        or header_lookup.get("x-balance-remaining")
        or header_lookup.get("x-token-remaining")
    )

    if text:
        json_payload: dict[str, object] | None = None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                json_payload = parsed
        except Exception:
            json_payload = None

        if json_payload:
            if rate_limit_rpm is None:
                rate_limit_rpm = _as_int(
                    json_payload.get("rate_limit_rpm")
                    or json_payload.get("rateLimit")
                    or json_payload.get("limit_rpm")
                )
            if remaining_tokens is None:
                remaining_tokens = _as_float(
                    json_payload.get("remaining_tokens")
                    or json_payload.get("remainingTokens")
                    or json_payload.get("remaining")
                    or json_payload.get("balance")
                )

        if remaining_tokens is None:
            # Example: "[Balance left] 10000000"
            balance_match = re.search(
                r"(?:\[\s*balance\s*left\s*\]|balance\s*left)\s*[:\]]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
                text,
                flags=re.IGNORECASE,
            )
            if balance_match:
                remaining_tokens = _as_float(balance_match.group(1).replace(",", ""))

    return remaining_tokens, rate_limit_rpm, preview or None


def _resolve_downloader_base_path(
    *,
    input_path: str | None,
    default_path: str | None,
    field_name: str,
    project_name: str,
    required_dir: str,
) -> Path:
    normalized = (
        _normalize_optional_path(input_path)
        if input_path is not None
        else _normalize_optional_path(default_path)
    )
    if not normalized:
        raise HTTPException(status_code=400, detail=f"缺少 {field_name}。")

    base_path = Path(normalized).expanduser()
    if not base_path.exists() or not base_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 无效（目录不存在）: {base_path}",
        )
    main_py = base_path / "main.py"
    if not main_py.exists() or not main_py.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"{project_name} 路径无效（缺少 main.py）: {main_py}",
        )
    package_root = base_path / required_dir
    if not package_root.exists() or not package_root.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"{project_name} 路径无效（缺少 {required_dir}/）: {package_root}",
        )
    return base_path


def _parse_json_tail_line(decoded: str) -> dict[str, object] | None:
    for line in reversed(decoded.splitlines()):
        one = line.strip()
        if not one.startswith("{") or not one.endswith("}"):
            continue
        try:
            payload = json.loads(one)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


async def _run_uv_sync(*, uv_path: str, base_path: Path, project_name: str) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            uv_path,
            "sync",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(base_path),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=240)
    except TimeoutError:
        raise HTTPException(
            status_code=400,
            detail=f"{project_name} 校验超时（uv sync > 240s）: {uv_path}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法执行 uv sync: {uv_path} ({exc})",
        )

    if process.returncode != 0:
        detail_output = _format_process_output(stdout, stderr)
        raise HTTPException(
            status_code=400,
            detail=(
                f"{project_name} 校验失败（uv sync）。\n"
                f"uv: {uv_path}\n"
                f"path: {base_path}\n"
                f"输出：\n{detail_output}"
            ),
        )


async def _validate_xhs_downloader_runtime(
    xhs_downloader_path: str | None,
) -> tuple[str, str]:
    base_path = _resolve_downloader_base_path(
        input_path=xhs_downloader_path,
        default_path=settings.xhs_downloader_path,
        field_name="xhs_downloader_path",
        project_name="XHS-Downloader",
        required_dir="source",
    )
    uv_path = _resolve_uv_path()
    await _run_uv_sync(uv_path=uv_path, base_path=base_path, project_name="XHS-Downloader")

    script = r"""
import json
from source import XHS

print(json.dumps({"entry": "source.XHS", "class_name": XHS.__name__}, ensure_ascii=False))
"""
    try:
        process = await asyncio.create_subprocess_exec(
            uv_path,
            "run",
            "python",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(base_path),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        raise HTTPException(
            status_code=400,
            detail=f"XHS-Downloader 校验超时（uv run > 30s）: {uv_path}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法执行 uv: {uv_path} ({exc})",
        )

    if process.returncode != 0:
        detail_output = _format_process_output(stdout, stderr)
        raise HTTPException(
            status_code=400,
            detail=(
                "XHS-Downloader 校验失败。\n"
                f"uv: {uv_path}\n"
                f"path: {base_path}\n"
                f"输出：\n{detail_output}"
            ),
        )

    decoded = stdout.decode(errors="ignore").strip()
    payload = _parse_json_tail_line(decoded) or {}
    entry = str(payload.get("entry") or "source.XHS").strip() or "source.XHS"
    return uv_path, entry


async def _validate_tiktok_downloader_runtime(
    tiktok_downloader_path: str | None,
) -> tuple[str, str]:
    base_path = _resolve_downloader_base_path(
        input_path=tiktok_downloader_path,
        default_path=settings.tiktok_downloader_path,
        field_name="tiktok_downloader_path",
        project_name="TikTokDownloader",
        required_dir="src",
    )
    uv_path = _resolve_uv_path()
    await _run_uv_sync(uv_path=uv_path, base_path=base_path, project_name="TikTokDownloader")

    script = r"""
import json
from src.application import TikTokDownloader
from src.application.main_terminal import TikTok

print(
    json.dumps(
        {
            "entry": "src.application.TikTokDownloader + src.application.main_terminal.TikTok",
            "classes": [TikTokDownloader.__name__, TikTok.__name__],
        },
        ensure_ascii=False,
    )
)
"""
    try:
        process = await asyncio.create_subprocess_exec(
            uv_path,
            "run",
            "python",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(base_path),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        raise HTTPException(
            status_code=400,
            detail=f"TikTokDownloader 校验超时（uv run > 30s）: {uv_path}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法执行 uv: {uv_path} ({exc})",
        )

    if process.returncode != 0:
        detail_output = _format_process_output(stdout, stderr)
        raise HTTPException(
            status_code=400,
            detail=(
                "TikTokDownloader 校验失败。\n"
                f"uv: {uv_path}\n"
                f"path: {base_path}\n"
                f"输出：\n{detail_output}\n"
                "请确认路径指向可运行版本（上游部分版本存在语法问题）。"
            ),
        )

    decoded = stdout.decode(errors="ignore").strip()
    payload = _parse_json_tail_line(decoded) or {}
    entry = str(payload.get("entry") or "").strip()
    if not entry:
        entry = "src.application.TikTokDownloader + src.application.main_terminal.TikTok"
    return uv_path, entry


async def _validate_ks_downloader_runtime(
    ks_downloader_path: str | None,
) -> tuple[str, str]:
    base_path = _resolve_downloader_base_path(
        input_path=ks_downloader_path,
        default_path=settings.ks_downloader_path,
        field_name="ks_downloader_path",
        project_name="KS-Downloader",
        required_dir="source",
    )
    uv_path = _resolve_uv_path()
    await _run_uv_sync(uv_path=uv_path, base_path=base_path, project_name="KS-Downloader")

    script = r"""
import json
from source import KS

print(
    json.dumps(
        {
            "entry": "source.KS",
            "class_name": KS.__name__,
        },
        ensure_ascii=False,
    )
)
"""
    try:
        process = await asyncio.create_subprocess_exec(
            uv_path,
            "run",
            "python",
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(base_path),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        raise HTTPException(
            status_code=400,
            detail=f"KS-Downloader 校验超时（uv run > 30s）: {uv_path}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法执行 uv: {uv_path} ({exc})",
        )

    if process.returncode != 0:
        detail_output = _format_process_output(stdout, stderr)
        raise HTTPException(
            status_code=400,
            detail=(
                "KS-Downloader 校验失败。\n"
                f"uv: {uv_path}\n"
                f"path: {base_path}\n"
                f"输出：\n{detail_output}"
            ),
        )

    decoded = stdout.decode(errors="ignore").strip()
    payload = _parse_json_tail_line(decoded) or {}
    entry = str(payload.get("entry") or "source.KS").strip() or "source.KS"
    return uv_path, entry


async def _validate_wan2gp_runtime(
    wan2gp_path: str | None,
    local_model_python_path: str | None,
) -> tuple[str, str]:
    if not wan2gp_path:
        raise HTTPException(
            status_code=400,
            detail="缺少 wan2gp_path。",
        )

    base_path = Path(wan2gp_path).expanduser()
    if not base_path.exists() or not base_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"wan2gp_path 无效（目录不存在）: {base_path}",
        )

    wgp_script = base_path / "wgp.py"
    if not wgp_script.exists() or not wgp_script.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"wan2gp_path 下未找到 wgp.py: {wgp_script}",
        )

    python_path = _resolve_local_model_python_path(local_model_python_path)

    try:
        process = await asyncio.create_subprocess_exec(
            str(python_path),
            "-c",
            "import torch; print(torch.__version__)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        raise HTTPException(
            status_code=400,
            detail=f"共享 Python 路径校验超时（import torch > 20s）: {python_path}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"无法执行共享 Python 路径: {python_path} ({exc})",
        )

    if process.returncode != 0:
        detail_output = _format_process_output(stdout, stderr)
        raise HTTPException(
            status_code=400,
            detail=(
                "local_model_python_path 校验失败：无法 import torch。\n"
                f"python: {python_path}\n"
                f"输出：\n{detail_output}"
            ),
        )

    torch_version = (stdout.decode(errors="ignore").strip().splitlines() or ["unknown"])[-1]
    return str(python_path), torch_version


def _build_default_trial_audio(sample_path: Path) -> None:
    # 默认样例：2.2 秒双频正弦波。用于验证 faster-whisper 能否完整跑通。
    sample_rate = 16000
    duration_seconds = 2.2
    total_frames = int(sample_rate * duration_seconds)
    with wave.open(str(sample_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(total_frames):
            t = i / sample_rate
            amp = 0.35 * math.sin(2 * math.pi * 440 * t) + 0.2 * math.sin(2 * math.pi * 660 * t)
            amp = max(-0.95, min(0.95, amp))
            frames.extend(struct.pack("<h", int(amp * 32767)))
        wav_file.writeframes(frames)


def _normalize_volcengine_speech_language(value: str | None) -> str | None:
    text = str(value or settings.speech_volcengine_language or "").strip()
    return text or None


def _truncate_volcengine_error_text(value: str, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:300]} ... {text[-200:]}"


def _extract_volcengine_status_code(
    response: httpx.Response, payload: dict[str, object]
) -> int | None:
    candidates: list[object] = [
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


def _extract_volcengine_status_message(response: httpx.Response, payload: dict[str, object]) -> str:
    candidates: list[object] = [
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
    payload: dict[str, object],
    *,
    fallback: str,
) -> str:
    candidates: list[object] = [
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


def _resolve_volcengine_speech_credentials(
    *,
    app_key: str | None,
    access_key: str | None,
    resource_id: str | None,
    language: str | None,
) -> tuple[str, str, str, str | None]:
    resolved_app_key = str(app_key or settings.speech_volcengine_app_key or "").strip()
    resolved_access_key = str(access_key or settings.speech_volcengine_access_key or "").strip()
    resolved_resource_id = (
        str(resource_id or settings.speech_volcengine_resource_id or "volc.seedasr.auc").strip()
        or "volc.seedasr.auc"
    )
    resolved_language = _normalize_volcengine_speech_language(language)
    if not resolved_app_key:
        raise HTTPException(status_code=400, detail="缺少火山语音识别 app_key")
    if not resolved_access_key:
        raise HTTPException(status_code=400, detail="缺少火山语音识别 access_key")
    if not resolved_resource_id:
        raise HTTPException(status_code=400, detail="缺少火山语音识别 resource_id")
    return resolved_app_key, resolved_access_key, resolved_resource_id, resolved_language


async def _validate_volcengine_speech_runtime(
    *,
    app_key: str | None,
    access_key: str | None,
    resource_id: str | None,
    language: str | None,
) -> tuple[str, str, str | None, int, int, str, int]:
    resolved_app_key, resolved_access_key, resolved_resource_id, resolved_language = (
        _resolve_volcengine_speech_credentials(
            app_key=app_key,
            access_key=access_key,
            resource_id=resource_id,
            language=language,
        )
    )

    with tempfile.TemporaryDirectory(prefix="localvideo_asr_") as tmp_dir:
        sample_path = Path(tmp_dir) / "volcengine_speech_sample.wav"
        _build_default_trial_audio(sample_path)
        audio_bytes = sample_path.read_bytes()

    submit_request_id = uuid4().hex
    submit_headers = {
        "X-Api-App-Key": resolved_app_key,
        "X-Api-Access-Key": resolved_access_key,
        "X-Api-Resource-Id": resolved_resource_id,
        "X-Api-Request-Id": submit_request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json",
    }
    submit_payload = {
        "user": {"uid": "localvideo-settings-validate"},
        "audio": {
            "format": "wav",
            "data": base64.b64encode(audio_bytes).decode("ascii"),
        },
        "request": {"model_name": "bigmodel"},
    }
    if resolved_language:
        submit_payload["audio"]["language"] = resolved_language

    started = time.monotonic()
    response_body: dict[str, object] = {}
    final_status_code: int | None = None
    try:
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            submit_response = await client.post(
                VOLCENGINE_ASR_SUBMIT_ENDPOINT,
                headers=submit_headers,
                json=submit_payload,
            )
            submit_response.raise_for_status()
            try:
                raw_submit_body = submit_response.json()
            except Exception:
                raw_submit_body = {}
            submit_body = raw_submit_body if isinstance(raw_submit_body, dict) else {}
            submit_status_code = _extract_volcengine_status_code(submit_response, submit_body)
            if submit_status_code not in (None, 0, VOLCENGINE_ASR_SUCCESS_STATUS_CODE):
                submit_message = _extract_volcengine_status_message(submit_response, submit_body)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "火山语音识别校验失败（提交任务失败）"
                        f" code={submit_status_code}: {submit_message or 'unknown'}"
                    ),
                )

            query_request_id = _extract_volcengine_task_request_id(
                submit_response,
                submit_body,
                fallback=submit_request_id,
            )
            query_headers = {
                "X-Api-App-Key": resolved_app_key,
                "X-Api-Access-Key": resolved_access_key,
                "X-Api-Resource-Id": resolved_resource_id,
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
                    raw_query_body = query_response.json()
                except Exception as exc:
                    raise HTTPException(
                        status_code=400, detail="火山语音识别响应不是合法 JSON"
                    ) from exc
                if not isinstance(raw_query_body, dict):
                    raise HTTPException(
                        status_code=400, detail="火山语音识别响应格式错误（非对象）"
                    )
                response_body = raw_query_body
                final_status_code = _extract_volcengine_status_code(query_response, response_body)
                if final_status_code in VOLCENGINE_ASR_PENDING_STATUS_CODES:
                    if time.monotonic() >= deadline:
                        raise HTTPException(
                            status_code=400,
                            detail=f"火山语音识别校验超时（>{int(VOLCENGINE_ASR_QUERY_TIMEOUT_SECONDS)}s）",
                        )
                    await asyncio.sleep(VOLCENGINE_ASR_QUERY_POLL_SECONDS)
                    continue
                if final_status_code in (None, 0, VOLCENGINE_ASR_SUCCESS_STATUS_CODE):
                    break
                if final_status_code == VOLCENGINE_ASR_SILENCE_STATUS_CODE:
                    break

                query_message = _extract_volcengine_status_message(query_response, response_body)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "火山语音识别校验失败（查询任务失败）"
                        f" code={final_status_code}: {query_message or 'unknown'}"
                    ),
                )
    except httpx.HTTPStatusError as exc:
        body = _truncate_volcengine_error_text(exc.response.text or "")
        raise HTTPException(
            status_code=400,
            detail=f"火山语音识别校验失败（HTTP {exc.response.status_code}）: {body or '<empty>'}",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"火山语音识别连接失败: {exc}") from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)

    result = response_body.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    if not isinstance(result, dict):
        result = {}

    utterance_count = 0
    word_count = 0
    preview_tokens: list[str] = []
    utterances = result.get("utterances")
    if isinstance(utterances, list):
        utterance_count = len(utterances)
        for utterance in utterances:
            if not isinstance(utterance, dict):
                continue
            text = str(utterance.get("text") or "").strip()
            if text:
                preview_tokens.append(text)
            words = utterance.get("words")
            if isinstance(words, list):
                word_count += len([item for item in words if isinstance(item, dict)])

    if word_count <= 0:
        words = result.get("words")
        if isinstance(words, list):
            word_count = len([item for item in words if isinstance(item, dict)])
            for word in words:
                if not isinstance(word, dict):
                    continue
                token = str(word.get("text") or word.get("word") or "").strip()
                if token:
                    preview_tokens.append(token)
                    if len(preview_tokens) >= 32:
                        break

    preview_text = " ".join(preview_tokens).strip()
    if len(preview_text) > 200:
        preview_text = preview_text[:200]
    return (
        _mask_key(resolved_app_key),
        resolved_resource_id,
        resolved_language,
        utterance_count,
        word_count,
        preview_text,
        elapsed_ms,
    )


async def _validate_faster_whisper_runtime(
    model: str | None,
) -> tuple[str, str, str, int, int, str, int]:
    try:
        model_name = resolve_faster_whisper_model_name(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="localvideo_fw_") as tmp_dir:
        sample_path = Path(tmp_dir) / "faster_whisper_default_sample.wav"
        _build_default_trial_audio(sample_path)
        try:
            result = await transcribe_with_faster_whisper(
                sample_path,
                model=model_name,
            )
        except TimeoutError:
            raise HTTPException(status_code=400, detail="faster-whisper 校验超时（>180s）")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"faster-whisper 校验失败: {exc}") from exc

    return (
        result.model,
        result.device,
        result.compute_type,
        result.utterance_count,
        result.word_count,
        result.preview_text,
        result.elapsed_ms,
    )


async def _validate_crawl4ai_runtime() -> tuple[str, str]:
    try:
        return await validate_crawl4ai_installation()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _get_nested(data: dict, path: tuple[str, ...]):
    cursor = data
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def _pick_first_float(data: dict, paths: list[tuple[str, ...]]) -> float | None:
    for path in paths:
        value = _get_nested(data, path)
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_tavily_usage(
    payload: dict,
) -> tuple[
    float | None,
    float | None,
    float | None,
    str | None,
    str | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    account_remaining = _pick_first_float(
        payload,
        [
            ("account", "plan_remaining"),
            ("account", "remaining"),
            ("account", "credits_remaining"),
        ],
    )
    account_used = _pick_first_float(
        payload,
        [
            ("account", "plan_usage"),
            ("account", "usage"),
            ("account", "used_credits"),
        ],
    )
    account_total = _pick_first_float(
        payload,
        [
            ("account", "plan_limit"),
            ("account", "limit"),
            ("account", "total_credits"),
        ],
    )

    key_remaining = _pick_first_float(
        payload,
        [
            ("remaining_credits",),
            ("credits_remaining",),
            ("credits", "remaining"),
            ("usage", "credits_remaining"),
            ("usage", "remaining_credits"),
            ("balance",),
            ("remaining",),
            ("key", "remaining"),
        ],
    )
    key_used = _pick_first_float(
        payload,
        [
            ("used_credits",),
            ("credits_used",),
            ("credits", "used"),
            ("usage", "credits_used"),
            ("usage", "used_credits"),
            ("current_period_usage",),
            ("usage",),
            ("key", "usage"),
        ],
    )
    key_total = _pick_first_float(
        payload,
        [
            ("total_credits",),
            ("credits_total",),
            ("credits", "total"),
            ("usage_limit",),
            ("current_period_limit",),
            ("plan", "credits"),
            ("limit",),
            ("key", "limit"),
        ],
    )
    if account_remaining is None and account_total is not None and account_used is not None:
        account_remaining = max(0.0, account_total - account_used)
    if account_total is None and account_remaining is not None and account_used is not None:
        account_total = account_remaining + account_used

    if key_remaining is None and key_total is not None and key_used is not None:
        key_remaining = max(0.0, key_total - key_used)
    if key_total is None and key_remaining is not None and key_used is not None:
        key_total = key_remaining + key_used

    source = "account" if (account_total is not None or account_used is not None) else "key"
    if source == "account":
        remaining = account_remaining
        used = account_used
        total = account_total
    else:
        remaining = key_remaining
        used = key_used
        total = key_total

    reset_at = (
        payload.get("reset_at")
        or payload.get("period_end")
        or payload.get("current_period_end")
        or payload.get("next_reset")
    )
    return (
        remaining,
        used,
        total,
        str(reset_at) if reset_at is not None else None,
        source,
        account_remaining,
        account_used,
        account_total,
        key_remaining,
        key_used,
        key_total,
    )


@router.post("/wan2gp/validate", response_model=Wan2GPValidateResponse)
async def validate_wan2gp_runtime(
    payload: Wan2GPValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    if "wan2gp_path" in data:
        wan2gp_path = _normalize_optional_path(data.get("wan2gp_path"))
    else:
        wan2gp_path = settings.wan2gp_path

    if "local_model_python_path" in data:
        local_model_python_path = _normalize_optional_path(data.get("local_model_python_path"))
    else:
        local_model_python_path = settings.local_model_python_path

    ready_for_validation = bool(
        _normalize_optional_path(wan2gp_path) and _normalize_optional_path(local_model_python_path)
    )
    try:
        python_path, torch_version = await _validate_wan2gp_runtime(
            wan2gp_path=wan2gp_path,
            local_model_python_path=local_model_python_path,
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="wan2gp_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="wan2gp_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return Wan2GPValidateResponse(
        valid=True,
        wan2gp_path=str(Path(wan2gp_path).expanduser()),
        python_path=python_path,
        torch_version=torch_version,
    )


@router.post("/faster-whisper/validate", response_model=FasterWhisperValidateResponse)
async def validate_faster_whisper_runtime(
    payload: FasterWhisperValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    ready_for_validation = True
    try:
        (
            model_name,
            device,
            compute_type,
            utterance_count,
            word_count,
            preview_text,
            elapsed_ms,
        ) = await _validate_faster_whisper_runtime(
            model=payload.model,
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="faster_whisper_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="faster_whisper_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return FasterWhisperValidateResponse(
        valid=True,
        model=model_name,
        device=device,
        compute_type=compute_type,
        elapsed_ms=elapsed_ms,
        utterance_count=utterance_count,
        word_count=word_count,
        preview_text=preview_text,
    )


@router.post("/speech/volcengine_asr/test", response_model=VolcengineSpeechValidateResponse)
async def validate_volcengine_speech_runtime(
    payload: VolcengineSpeechValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    resolved_app_key = str(payload.app_key or settings.speech_volcengine_app_key or "").strip()
    resolved_access_key = str(
        payload.access_key or settings.speech_volcengine_access_key or ""
    ).strip()
    resolved_resource_id = str(
        payload.resource_id or settings.speech_volcengine_resource_id or "volc.seedasr.auc"
    ).strip()
    ready_for_validation = bool(resolved_app_key and resolved_access_key and resolved_resource_id)

    try:
        (
            app_key_masked,
            resource_id,
            language,
            utterance_count,
            word_count,
            preview_text,
            elapsed_ms,
        ) = await _validate_volcengine_speech_runtime(
            app_key=payload.app_key,
            access_key=payload.access_key,
            resource_id=payload.resource_id,
            language=payload.language,
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="speech_volcengine_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="speech_volcengine_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return VolcengineSpeechValidateResponse(
        valid=True,
        app_key_masked=app_key_masked,
        resource_id=resource_id,
        language=language,
        elapsed_ms=elapsed_ms,
        utterance_count=utterance_count,
        word_count=word_count,
        preview_text=preview_text,
    )


@router.post("/crawl4ai/validate", response_model=Crawl4AIValidateResponse)
async def validate_crawl4ai_runtime(
    payload: Crawl4AIValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    ready_for_validation = True
    try:
        command_path, output_preview = await _validate_crawl4ai_runtime()
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="crawl4ai_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise
    await _persist_runtime_validation_status(
        db,
        key="crawl4ai_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return Crawl4AIValidateResponse(
        valid=True,
        command_path=command_path,
        command="crawl4ai-doctor",
        output_preview=output_preview,
    )


@router.post("/xhs-downloader/validate", response_model=XHSDownloaderValidateResponse)
async def validate_xhs_downloader_runtime(
    payload: XHSDownloaderValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    ready_for_validation = bool(
        _normalize_optional_path(payload.xhs_downloader_path)
        or _normalize_optional_path(settings.xhs_downloader_path)
    )
    try:
        uv_path, entry = await _validate_xhs_downloader_runtime(
            xhs_downloader_path=payload.xhs_downloader_path,
        )
        base_path = _resolve_downloader_base_path(
            input_path=payload.xhs_downloader_path,
            default_path=settings.xhs_downloader_path,
            field_name="xhs_downloader_path",
            project_name="XHS-Downloader",
            required_dir="source",
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="xhs_downloader_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="xhs_downloader_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return XHSDownloaderValidateResponse(
        valid=True,
        xhs_downloader_path=str(base_path),
        uv_path=uv_path,
        entry=entry,
    )


@router.post("/tiktok-downloader/validate", response_model=TikTokDownloaderValidateResponse)
async def validate_tiktok_downloader_runtime(
    payload: TikTokDownloaderValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    ready_for_validation = bool(
        _normalize_optional_path(payload.tiktok_downloader_path)
        or _normalize_optional_path(settings.tiktok_downloader_path)
    )
    try:
        uv_path, entry = await _validate_tiktok_downloader_runtime(
            tiktok_downloader_path=payload.tiktok_downloader_path,
        )
        base_path = _resolve_downloader_base_path(
            input_path=payload.tiktok_downloader_path,
            default_path=settings.tiktok_downloader_path,
            field_name="tiktok_downloader_path",
            project_name="TikTokDownloader",
            required_dir="src",
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="tiktok_downloader_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="tiktok_downloader_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return TikTokDownloaderValidateResponse(
        valid=True,
        tiktok_downloader_path=str(base_path),
        uv_path=uv_path,
        entry=entry,
    )


@router.post("/ks-downloader/validate", response_model=KSDownloaderValidateResponse)
async def validate_ks_downloader_runtime(
    payload: KSDownloaderValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    ready_for_validation = bool(
        _normalize_optional_path(payload.ks_downloader_path)
        or _normalize_optional_path(settings.ks_downloader_path)
    )
    try:
        uv_path, entry = await _validate_ks_downloader_runtime(
            ks_downloader_path=payload.ks_downloader_path,
        )
        base_path = _resolve_downloader_base_path(
            input_path=payload.ks_downloader_path,
            default_path=settings.ks_downloader_path,
            field_name="ks_downloader_path",
            project_name="KS-Downloader",
            required_dir="source",
        )
    except Exception:
        await _persist_runtime_validation_status(
            db,
            key="ks_downloader_validation_status",
            status=_runtime_component_status(ready=ready_for_validation, success=False),
        )
        raise

    await _persist_runtime_validation_status(
        db,
        key="ks_downloader_validation_status",
        status=_runtime_component_status(ready=ready_for_validation, success=True),
    )
    return KSDownloaderValidateResponse(
        valid=True,
        ks_downloader_path=str(base_path),
        uv_path=uv_path,
        entry=entry,
    )


@router.post("/jina-reader/usage", response_model=JinaReaderUsageResponse)
async def get_jina_reader_usage(
    payload: JinaReaderUsageRequest,
):
    remaining_tokens, rate_limit_rpm, raw_preview = await _fetch_jina_reader_usage(
        payload.jina_reader_api_key
    )
    return JinaReaderUsageResponse(
        available=True,
        remaining_tokens=remaining_tokens,
        rate_limit_rpm=rate_limit_rpm,
        raw_preview=raw_preview,
    )


@router.get("/tavily/usage", response_model=TavilyUsageResponse)
async def get_tavily_usage():
    if not settings.search_tavily_api_key:
        return TavilyUsageResponse(available=False)
    masked_key = _mask_key(settings.search_tavily_api_key)
    logger.info("[TavilyUsage] using key: %s", masked_key)

    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            response = await client.get(
                "https://api.tavily.com/usage",
                headers={
                    "Authorization": f"Bearer {settings.search_tavily_api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                payload = {"raw": payload}
            logger.info(
                "[TavilyUsage] raw response: %s",
                json.dumps(payload, ensure_ascii=False),
            )
            (
                remaining,
                used,
                total,
                reset_at,
                source,
                account_remaining,
                account_used,
                account_total,
                key_remaining,
                key_used,
                key_total,
            ) = _extract_tavily_usage(payload)
            logger.info(
                "[TavilyUsage] selected source=%s remaining=%s used=%s total=%s "
                "account(remaining=%s used=%s total=%s) key(remaining=%s used=%s total=%s)",
                source,
                remaining,
                used,
                total,
                account_remaining,
                account_used,
                account_total,
                key_remaining,
                key_used,
                key_total,
            )
            return TavilyUsageResponse(
                available=True,
                remaining_credits=remaining,
                used_credits=used,
                total_credits=total,
                source=source,
                account_used_credits=account_used,
                account_total_credits=account_total,
                account_remaining_credits=account_remaining,
                key_used_credits=key_used,
                key_total_credits=key_total,
                key_remaining_credits=key_remaining,
                reset_at=reset_at,
                raw=payload,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Tavily usage request timeout")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            body = e.response.json()
            detail = str(body.get("detail") or body.get("error") or body)
        except Exception:
            detail = e.response.text
        raise HTTPException(
            status_code=e.response.status_code,
            detail=detail or str(e),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Tavily usage: {e}")
