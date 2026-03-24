from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def build_temporary_output_path(target_path: Path) -> Path:
    token = uuid4().hex[:12]
    suffix = target_path.suffix
    return target_path.with_name(f".{target_path.stem}.tmp.{token}{suffix}")


def resolve_final_output_path(target_path: Path, generated_path: Path) -> Path:
    generated_suffix = generated_path.suffix
    if generated_suffix and generated_suffix.lower() != target_path.suffix.lower():
        return target_path.with_suffix(generated_suffix.lower())
    return target_path


def replace_generated_file(generated_path: Path, target_path: Path) -> Path:
    if not generated_path.exists():
        raise FileNotFoundError(f"Generated file not found: {generated_path}")
    final_path = resolve_final_output_path(target_path, generated_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if generated_path != final_path:
        generated_path.replace(final_path)
    return final_path


def cleanup_temp_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
