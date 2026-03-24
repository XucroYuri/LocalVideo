from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import StageRuntimeError
from app.stages.common.paths import resolve_path_for_io

from ._audio_config import normalize_speed

AUDIO_SOURCE_POLICY_VERSION = "unified_source_v1"
AUDIO_RENDER_POLICY_VERSION = "unified_render_v1"
SOURCE_AUDIO_SPEED = 1.0


@dataclass
class AudioCacheReuse:
    reuse_render: bool
    reuse_source: bool
    render_file_path: Path | None
    source_file_path: Path | None


def resolve_audio_output_extension(provider_name: str) -> str:
    return ".wav" if str(provider_name or "").strip().lower() == "wan2gp" else ".mp3"


def build_source_audio_path(render_output_path: Path) -> Path:
    return render_output_path.with_name(
        f"{render_output_path.stem}.source{render_output_path.suffix}"
    )


def build_audio_source_signature(
    *,
    provider_name: str,
    text: str,
    config: dict[str, Any],
) -> str:
    payload = {
        "provider": str(provider_name or "").strip().lower(),
        "text_sha256": hashlib.sha256((text or "").encode("utf-8")).hexdigest(),
        "config": _normalize_signature_value(config),
        "source_policy_version": AUDIO_SOURCE_POLICY_VERSION,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_audio_render_signature(
    *,
    audio_source_signature: str,
    speed: float,
) -> str:
    payload = {
        "audio_source_signature": str(audio_source_signature or "").strip(),
        "audio_speed": round(float(normalize_speed(speed, SOURCE_AUDIO_SPEED)), 6),
        "render_policy_version": AUDIO_RENDER_POLICY_VERSION,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve_audio_cache_reuse(
    *,
    existing_asset: dict[str, Any] | None,
    audio_source_signature: str,
    audio_render_signature: str,
    force_regenerate: bool,
) -> AudioCacheReuse:
    if not isinstance(existing_asset, dict):
        return AudioCacheReuse(
            reuse_render=False,
            reuse_source=False,
            render_file_path=None,
            source_file_path=None,
        )

    render_file_path = _resolve_existing_file(existing_asset.get("file_path"))
    source_file_path = _resolve_existing_file(existing_asset.get("source_file_path"))

    existing_source_signature = str(existing_asset.get("audio_source_signature") or "").strip()
    existing_render_signature = str(existing_asset.get("audio_render_signature") or "").strip()

    can_reuse_source = (
        source_file_path is not None
        and existing_source_signature
        and existing_source_signature == str(audio_source_signature or "").strip()
    )
    can_reuse_render = (
        not force_regenerate
        and render_file_path is not None
        and existing_render_signature
        and existing_render_signature == str(audio_render_signature or "").strip()
    )

    return AudioCacheReuse(
        reuse_render=can_reuse_render,
        reuse_source=can_reuse_source,
        render_file_path=render_file_path,
        source_file_path=source_file_path,
    )


async def render_audio_from_source(
    *,
    source_file_path: Path,
    output_path: Path,
    speed: float,
) -> Path:
    if not source_file_path.exists():
        raise FileNotFoundError(f"Audio source file not found: {source_file_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_output_path = output_path.with_name(f"{output_path.stem}.render_tmp{output_path.suffix}")
    tmp_output_path.unlink(missing_ok=True)

    normalized_speed = normalize_speed(speed, SOURCE_AUDIO_SPEED)
    if abs(normalized_speed - SOURCE_AUDIO_SPEED) < 1e-3:
        shutil.copy2(str(source_file_path), str(tmp_output_path))
    else:
        factors = _build_atempo_factors(normalized_speed)
        filter_expr = ",".join(f"atempo={factor:.6f}" for factor in factors)
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(source_file_path),
            "-filter:a",
            filter_expr,
            "-vn",
            str(tmp_output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not tmp_output_path.exists():
            error_text = stderr.decode(errors="ignore").strip()
            raise StageRuntimeError(
                f"音频变速渲染失败 (speed={normalized_speed:.3f}): {error_text}"
            )

    if output_path.exists():
        output_path.unlink()
    shutil.move(str(tmp_output_path), str(output_path))
    return output_path


def extract_audio_asset_paths(asset: dict[str, Any] | None) -> list[str]:
    if not isinstance(asset, dict):
        return []
    candidates = [
        asset.get("file_path"),
        asset.get("source_file_path"),
    ]
    paths: list[str] = []
    for item in candidates:
        text = str(item or "").strip()
        if text and text not in paths:
            paths.append(text)
    return paths


def cleanup_audio_file_variants(*, target_path: Path, keep_path: Path | None) -> None:
    directory = target_path.parent
    if not directory.exists():
        return
    keep_resolved = (
        str(keep_path.resolve()) if keep_path is not None and keep_path.exists() else None
    )
    pattern = f"{target_path.stem}.*"
    for candidate in directory.glob(pattern):
        if not candidate.is_file():
            continue
        if candidate.stem != target_path.stem:
            continue
        if keep_resolved is not None and str(candidate.resolve()) == keep_resolved:
            continue
        candidate.unlink(missing_ok=True)


def _normalize_signature_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_signature_value(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_normalize_signature_value(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Path):
        return str(value)
    return value


def _resolve_existing_file(path_value: Any) -> Path | None:
    resolved = resolve_path_for_io(path_value)
    if resolved is None or not resolved.exists():
        return None
    return resolved


def _build_atempo_factors(speed: float) -> list[float]:
    factors: list[float] = []
    remaining = float(speed)
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return factors
