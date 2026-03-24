from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=16)
def _load_defaults_payloads(
    wan2gp_root: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload_by_stem: dict[str, dict[str, Any]] = {}
    payload_by_architecture: dict[str, dict[str, Any]] = {}
    defaults_dir = Path(wan2gp_root).expanduser() / "defaults"
    if not defaults_dir.exists() or not defaults_dir.is_dir():
        return payload_by_stem, payload_by_architecture

    for config_file in sorted(defaults_dir.glob("*.json")):
        try:
            payload = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload_by_stem[config_file.stem] = payload
        model_info = payload.get("model")
        if isinstance(model_info, dict):
            architecture = str(model_info.get("architecture") or "").strip()
            if architecture and architecture not in payload_by_architecture:
                payload_by_architecture[architecture] = payload
    return payload_by_stem, payload_by_architecture


def _is_model_reference(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if "://" in value or "/" in value or "\\" in value:
        return False
    if "." in value:
        return False
    return True


def _normalize_url_groups(raw: Any) -> list[list[str]]:
    groups: list[list[str]] = []
    if raw is None:
        return groups
    if isinstance(raw, str):
        normalized = raw.strip()
        if normalized:
            groups.append([normalized])
        return groups
    if isinstance(raw, list):
        if raw and all(isinstance(item, str) for item in raw):
            choices = [item.strip() for item in raw if item and item.strip()]
            if choices:
                groups.append(choices)
            return groups
        for item in raw:
            groups.extend(_normalize_url_groups(item))
        return groups
    if isinstance(raw, dict):
        for key in ("URLs", "URLs2", "modules", "loras"):
            groups.extend(_normalize_url_groups(raw.get(key)))
    return groups


def _collect_required_url_groups(
    model_type: str,
    payload_by_stem: dict[str, dict[str, Any]],
    payload_by_architecture: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> list[list[str]]:
    visited = visited or set()
    if model_type in visited:
        return []
    visited.add(model_type)

    payload = payload_by_stem.get(model_type)
    if payload is None:
        payload = payload_by_architecture.get(model_type)
    if payload is None:
        return []

    model = payload.get("model")
    if not isinstance(model, dict):
        return []

    groups: list[list[str]] = []
    groups.extend(_normalize_url_groups(model.get("URLs")))
    groups.extend(_normalize_url_groups(model.get("modules")))
    groups.extend(_normalize_url_groups(model.get("loras")))

    preload_urls = model.get("preload_URLs")
    if isinstance(preload_urls, str):
        preload_value = preload_urls.strip()
        if preload_value:
            if _is_model_reference(preload_value):
                groups.extend(
                    _collect_required_url_groups(
                        preload_value,
                        payload_by_stem,
                        payload_by_architecture,
                        visited=visited,
                    )
                )
            else:
                groups.extend(_normalize_url_groups(preload_value))
    elif isinstance(preload_urls, list):
        for item in preload_urls:
            if isinstance(item, str):
                preload_value = item.strip()
                if not preload_value:
                    continue
                if _is_model_reference(preload_value):
                    groups.extend(
                        _collect_required_url_groups(
                            preload_value,
                            payload_by_stem,
                            payload_by_architecture,
                            visited=visited,
                        )
                    )
                else:
                    groups.extend(_normalize_url_groups(preload_value))
            else:
                groups.extend(_normalize_url_groups(item))
    return groups


def is_model_cached(wan2gp_path: Path, model_type: str) -> bool | None:
    model_key = str(model_type or "").strip()
    if not model_key:
        return None

    payload_by_stem, payload_by_architecture = _load_defaults_payloads(
        str(wan2gp_path.expanduser())
    )
    required_groups = _collect_required_url_groups(
        model_key,
        payload_by_stem,
        payload_by_architecture,
    )
    if not required_groups:
        return None

    ckpts_dir = wan2gp_path.expanduser() / "ckpts"
    if not ckpts_dir.exists() or not ckpts_dir.is_dir():
        return False

    existing_files: set[str] = set()
    for path in ckpts_dir.rglob("*"):
        if path.is_file():
            existing_files.add(path.name)

    for group in required_groups:
        candidates = [Path(url).name for url in group if isinstance(url, str) and url.strip()]
        if not candidates:
            continue
        if not any(name in existing_files for name in candidates):
            return False
    return True
