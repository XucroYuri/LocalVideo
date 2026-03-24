from __future__ import annotations

from fastapi import UploadFile

from app.config import settings

DEFAULT_LIBRARY_BATCH_MAX_ITEMS = 50
DEFAULT_LIBRARY_BATCH_MAX_TOTAL_UPLOAD_MB = 1024


def get_library_batch_max_items() -> int:
    return max(
        1,
        int(
            getattr(settings, "library_batch_max_items", DEFAULT_LIBRARY_BATCH_MAX_ITEMS)
            or DEFAULT_LIBRARY_BATCH_MAX_ITEMS
        ),
    )


def get_library_batch_max_total_upload_mb() -> int:
    return max(
        1,
        int(
            getattr(
                settings,
                "library_batch_max_total_upload_mb",
                DEFAULT_LIBRARY_BATCH_MAX_TOTAL_UPLOAD_MB,
            )
            or DEFAULT_LIBRARY_BATCH_MAX_TOTAL_UPLOAD_MB
        ),
    )


def get_library_batch_max_total_upload_bytes() -> int:
    return get_library_batch_max_total_upload_mb() * 1024 * 1024


def get_upload_file_size(file: UploadFile) -> int:
    stream = getattr(file, "file", None)
    if stream is None:
        return 0
    try:
        current = stream.tell()
        stream.seek(0, 2)
        size = int(stream.tell() or 0)
        stream.seek(current)
        return max(0, size)
    except Exception:  # noqa: BLE001
        return 0
