"""Common base for all Wan2GP local providers (audio, image, video)."""

from __future__ import annotations

import sys
from pathlib import Path

from app.providers.wan2gp.model_cache import is_model_cached
from app.providers.wan2gp.progress import infer_runtime_status_message

COMMON_RESOLUTIONS = [
    "1920x1088",
    "1088x1920",
    "1920x832",
    "832x1920",
    "1024x1024",
    "1280x720",
    "720x1280",
    "1280x544",
    "544x1280",
    "1104x832",
    "832x1104",
    "960x960",
    "960x544",
    "544x960",
    "832x624",
    "624x832",
    "720x720",
    "832x480",
    "480x832",
    "512x512",
]


class Wan2GPBase:
    """Mixin providing shared infrastructure for Wan2GP providers.

    Subclasses must set ``self.wan2gp_path`` (Path) and
    ``self.python_executable`` (str | None) before calling these helpers.
    """

    wan2gp_path: Path
    python_executable: str | None

    def _validate_config(self) -> None:
        if not self.wan2gp_path.exists():
            raise ValueError(f"Wan2GP path does not exist: {self.wan2gp_path}")
        if not (self.wan2gp_path / "wgp.py").exists():
            raise ValueError(f"Wan2GP executable missing: {self.wan2gp_path / 'wgp.py'}")

    def _resolve_python_executable(self) -> str:
        if self.python_executable:
            configured = Path(self.python_executable).expanduser()
            if not configured.exists():
                raise ValueError(f"Wan2GP python executable does not exist: {configured}")
            return str(configured)

        candidates = [
            self.wan2gp_path / ".venv" / "bin" / "python",
            self.wan2gp_path / "venv" / "bin" / "python",
            self.wan2gp_path / "env" / "bin" / "python",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return sys.executable

    def _is_model_cached(self, model_type: str) -> bool | None:
        return is_model_cached(self.wan2gp_path, model_type)

    @staticmethod
    def _infer_runtime_status_message(line: str) -> str | None:
        return infer_runtime_status_message(line)
