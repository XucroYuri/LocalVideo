"""Shared Wan2GP runtime helpers."""

from .base import COMMON_RESOLUTIONS, Wan2GPBase
from .model_cache import is_model_cached
from .process_registry import (
    cleanup_wan2gp_runtime_processes,
    detect_external_wan2gp_ui_processes,
    register_wan2gp_pid,
    terminate_pid_tree,
    unregister_wan2gp_pid,
)
from .progress import (
    STATUS_GENERATING,
    STATUS_MODEL_DOWNLOADING,
    STATUS_MODEL_LOADING,
    STATUS_PREPARING,
    emit_bootstrap_status,
    extract_percent_from_text,
    infer_runtime_status_message,
    normalize_status_message,
    should_advance_status,
)

__all__ = [
    "COMMON_RESOLUTIONS",
    "STATUS_PREPARING",
    "STATUS_MODEL_DOWNLOADING",
    "STATUS_MODEL_LOADING",
    "STATUS_GENERATING",
    "Wan2GPBase",
    "cleanup_wan2gp_runtime_processes",
    "detect_external_wan2gp_ui_processes",
    "register_wan2gp_pid",
    "unregister_wan2gp_pid",
    "terminate_pid_tree",
    "is_model_cached",
    "emit_bootstrap_status",
    "extract_percent_from_text",
    "infer_runtime_status_message",
    "normalize_status_message",
    "should_advance_status",
]
