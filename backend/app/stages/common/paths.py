from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.core.storage_path import (
    normalize_storage_payload_for_persistence,
    resolve_storage_payload_for_io,
)
from app.core.storage_path import (
    resolve_existing_path_for_io as _resolve_existing_path_for_io,
)
from app.core.storage_path import (
    resolve_path_for_io as _resolve_path_for_io,
)
from app.core.storage_path import (
    to_storage_public_path as _to_storage_public_path,
)
from app.models.project import Project


def resolve_output_dir_value(output_dir: str | None) -> Path | None:
    resolved = _resolve_path_for_io(output_dir)
    if resolved is not None:
        return resolved
    raw = str(output_dir or "").strip()
    return Path(raw).expanduser() if raw else None


def to_storage_public_path(path: Path) -> str:
    normalized = _to_storage_public_path(path)
    if not normalized:
        raise ValueError(f"Path is not under storage root: {path}")
    return normalized


def resolve_path_for_io(path_value: str | Path | None) -> Path | None:
    return _resolve_path_for_io(path_value)


def resolve_existing_path_for_io(
    path_value: str | Path | None,
    *,
    allowed_suffixes: set[str] | None = None,
) -> Path | None:
    return _resolve_existing_path_for_io(path_value, allowed_suffixes=allowed_suffixes)


def normalize_stage_payload_for_persistence(payload: dict | list | None) -> dict | list | None:
    return normalize_storage_payload_for_persistence(payload)


def resolve_stage_payload_for_io(payload: dict | list | None) -> dict | list | None:
    return resolve_storage_payload_for_io(payload)


def get_output_dir(project: Project) -> Path:
    resolved = resolve_output_dir_value(project.output_dir)
    if resolved:
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
    base_dir = Path(settings.storage_path) / "projects" / str(project.id)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir
