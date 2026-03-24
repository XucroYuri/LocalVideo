"""Unified domain exception hierarchy for stage execution.

All exceptions raised during stage processing should inherit from
:class:`StageError` so that the pipeline runner can identify them as
domain errors and store their message in ``StageExecution.error_message``.

The pipeline already catches ``Exception`` as a catch-all, but using
typed exceptions allows callers to distinguish categories when needed
(e.g. logging, metrics, retry decisions).
"""

from __future__ import annotations


class StageError(Exception):
    """Base exception for all stage execution errors."""


class StageValidationError(StageError):
    """Raised when stage input data is missing or invalid.

    Examples: empty script, missing audio data, malformed JSON response.
    """


class StageRuntimeError(StageError):
    """Raised when an external tool or subprocess fails during stage execution.

    Examples: ffmpeg failure, timeout, missing binary.
    """


class ProviderError(StageError):
    """Raised when an external API provider returns an error.

    Examples: Vertex AI quota exceeded, TTS service timeout.
    """


class ServiceError(Exception):
    """Domain exception for service-layer operations that map to HTTP responses.

    Use this instead of ``fastapi.HTTPException`` inside service modules so that
    the service layer stays framework-agnostic.  A global exception handler in
    ``main.py`` converts these into proper HTTP responses automatically.
    """

    def __init__(self, status_code: int = 400, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
