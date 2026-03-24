from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings

STORAGE_PUBLIC_PREFIX = "/storage/"
_PATH_KEY_SUFFIXES = ("_path", "_dir", "_audio_guide")
_PATH_KEY_EXACT = {"output_dir"}


def _storage_root() -> Path:
    return Path(settings.storage_path).expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _looks_like_path_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if normalized in _PATH_KEY_EXACT:
        return True
    return normalized.endswith(_PATH_KEY_SUFFIXES)


def to_storage_public_path(raw_path: str | Path | None) -> str | None:
    if raw_path is None:
        return None

    raw = str(raw_path).strip()
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    if normalized == "/storage":
        return "/storage"
    if normalized.startswith(STORAGE_PUBLIC_PREFIX):
        relative = normalized[len(STORAGE_PUBLIC_PREFIX) :].strip("/")
        return f"{STORAGE_PUBLIC_PREFIX}{relative}" if relative else "/storage"

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return None

    resolved = candidate.resolve()
    storage_root = _storage_root()
    if not _is_within(resolved, storage_root):
        return None

    relative = resolved.relative_to(storage_root).as_posix().strip("/")
    return f"{STORAGE_PUBLIC_PREFIX}{relative}" if relative else "/storage"


def resolve_path_for_io(raw_path: str | Path | None) -> Path | None:
    if raw_path is None:
        return None

    raw = str(raw_path).strip()
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    if normalized == "/storage":
        return _storage_root()
    if normalized.startswith(STORAGE_PUBLIC_PREFIX):
        relative = normalized[len(STORAGE_PUBLIC_PREFIX) :].strip("/")
        return (_storage_root() / relative).resolve() if relative else _storage_root()

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return None


def resolve_existing_path_for_io(
    raw_path: str | Path | None,
    *,
    allowed_suffixes: set[str] | None = None,
) -> Path | None:
    resolved = resolve_path_for_io(raw_path)
    if resolved is None:
        return None
    if resolved.exists():
        return resolved

    parent = resolved.parent
    if not parent.exists():
        return resolved

    normalized_allowed_suffixes = (
        {str(suffix).lower() for suffix in allowed_suffixes if str(suffix).strip()}
        if allowed_suffixes
        else None
    )
    candidates = [
        candidate.resolve()
        for candidate in parent.glob(f"{resolved.stem}.*")
        if candidate.is_file()
        and (
            normalized_allowed_suffixes is None
            or candidate.suffix.lower() in normalized_allowed_suffixes
        )
    ]
    if not candidates:
        return resolved
    if len(candidates) == 1:
        return candidates[0]

    candidates.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates[0]


def _transform_storage_payload(
    value: Any,
    *,
    to_public: bool,
    path_hint: bool,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _transform_storage_payload(
                item,
                to_public=to_public,
                path_hint=_looks_like_path_key(str(key)),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _transform_storage_payload(item, to_public=to_public, path_hint=path_hint)
            for item in value
        ]
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    if to_public:
        if not path_hint and not raw.startswith("/storage") and not raw.startswith("storage/"):
            return value
        converted = to_storage_public_path(raw)
        return converted if converted is not None else value

    # to absolute (for runtime io)
    if not path_hint and not raw.startswith("/storage"):
        return value
    resolved = resolve_path_for_io(raw)
    return str(resolved) if resolved is not None else value


def normalize_storage_payload_for_persistence(value: Any) -> Any:
    return _transform_storage_payload(value, to_public=True, path_hint=False)


def resolve_storage_payload_for_io(value: Any) -> Any:
    return _transform_storage_payload(value, to_public=False, path_hint=False)
