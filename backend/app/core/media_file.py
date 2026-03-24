"""Shared media file utilities used by stage_service and reference_library_service."""

import logging
from pathlib import Path
from typing import Literal

from fastapi import UploadFile

from app.config import settings
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_EXT_MAP = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

ImageScene = Literal["reference", "frame"]


def validate_image_upload(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ServiceError(
            400,
            f"File type '{file.content_type}' not allowed. Allowed types: PNG, JPEG, WebP",
        )


def resolve_image_ext(content_type: str | None) -> str:
    return IMAGE_EXT_MAP.get(content_type or "", "png")


async def save_upload_file(file: UploadFile, output_path: Path) -> None:
    try:
        content = await file.read()
        with open(output_path, "wb") as f:
            f.write(content)
    except Exception as e:  # noqa: BLE001
        raise ServiceError(500, f"Failed to save file: {e}")


def safe_delete_file(file_path: str | None) -> bool:
    if not file_path:
        return False
    raw = str(file_path or "").strip()
    if not raw:
        return False
    if raw.startswith("/storage/"):
        relative = raw[len("/storage/") :].strip("/")
        path = (Path(settings.storage_path).expanduser().resolve() / relative).resolve()
    else:
        path = Path(raw).expanduser()
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception as e:
            logger.warning("Failed to delete file %s: %s", file_path, e)
    return False
