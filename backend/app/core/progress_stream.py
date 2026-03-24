"""Shared helpers for SSE progress polling.

Used by both PipelineEngine.poll_progress() and StageOrchestrationMixin.event_generator()
to eliminate duplicated output_data parsing and change detection logic.
"""

import json
from dataclasses import dataclass
from typing import Any

from app.core.runtime_progress import build_running_fallback_message
from app.models.stage import StageStatus, StageType


@dataclass
class StageSnapshot:
    """Parsed snapshot of stage progress data extracted from a StageExecution row."""

    progress: int
    last_item_complete: int | None
    total_items: int | None
    completed_items: int | None
    skipped_items: int | None
    generating_shots: dict[str, Any] | None
    progress_message: str | None
    generating_hash: str | None
    fallback_message: str


def parse_stage_snapshot(stage_row: Any, stage_type: StageType) -> StageSnapshot:
    """Parse a StageExecution row into a StageSnapshot.

    Handles JSON string→dict conversion for output_data, extracts generating_shots
    and progress_message, computes generating_hash, and builds fallback message.
    """
    progress = int(stage_row.progress or 0)

    generating_shots = None
    progress_message = None
    output_data_dict: dict[str, Any] | None = None

    if stage_row.output_data:
        output_data = stage_row.output_data
        if isinstance(output_data, str):
            try:
                output_data = json.loads(output_data)
            except Exception:
                output_data = None
        if isinstance(output_data, dict):
            output_data_dict = output_data
            generating_shots = output_data.get("generating_shots")
            message_val = output_data.get("progress_message")
            if isinstance(message_val, str) and message_val.strip():
                progress_message = message_val.strip()

    generating_hash: str | None = None
    if generating_shots is not None:
        try:
            generating_hash = json.dumps(generating_shots, sort_keys=True, ensure_ascii=False)
        except Exception:
            pass

    fallback_message = build_running_fallback_message(
        stage_type=stage_type,
        progress=progress,
        input_data=stage_row.input_data,
        output_data=output_data_dict,
    )

    return StageSnapshot(
        progress=progress,
        last_item_complete=stage_row.last_item_complete,
        total_items=stage_row.total_items,
        completed_items=stage_row.completed_items,
        skipped_items=stage_row.skipped_items,
        generating_shots=generating_shots,
        progress_message=progress_message,
        generating_hash=generating_hash,
        fallback_message=fallback_message,
    )


class ProgressChangeTracker:
    """Tracks stage progress state and detects meaningful changes for SSE emission."""

    def __init__(self, initial_progress: int = -1, heartbeat_threshold: int = 30):
        self.last_progress: int = initial_progress
        self.last_item_complete: int | None = None
        self.last_progress_message: str | None = None
        self.last_generating_hash: str | None = None
        self.heartbeat_counter: int = 0
        self.heartbeat_threshold = heartbeat_threshold

    def detect_change(self, snapshot: StageSnapshot) -> bool:
        """Check if the snapshot represents a meaningful change worth emitting.

        Does NOT update internal state — call accept() after emitting.
        """
        if snapshot.progress != self.last_progress:
            return True
        if (
            snapshot.last_item_complete is not None
            and snapshot.last_item_complete >= 0
            and snapshot.last_item_complete != self.last_item_complete
        ):
            return True
        if snapshot.progress_message and snapshot.progress_message != self.last_progress_message:
            return True
        if (
            snapshot.generating_hash is not None
            and snapshot.generating_hash != self.last_generating_hash
        ):
            return True
        # Heartbeat
        self.heartbeat_counter += 1
        if self.heartbeat_counter >= self.heartbeat_threshold:
            return True
        return False

    def accept(self, snapshot: StageSnapshot) -> None:
        """Update tracked state after emitting a progress event."""
        self.last_progress = snapshot.progress
        if snapshot.last_item_complete is not None and snapshot.last_item_complete >= 0:
            self.last_item_complete = snapshot.last_item_complete
        self.last_progress_message = snapshot.progress_message
        self.last_generating_hash = snapshot.generating_hash
        self.heartbeat_counter = 0


def build_status_message(
    snap: StageSnapshot,
    status: StageStatus,
    error_message: str | None = None,
) -> str:
    """Build event message based on stage status and progress snapshot.

    Used by SSE event generators to construct the appropriate message
    for each progress event.
    """
    if snap.progress_message and status in {StageStatus.RUNNING, StageStatus.PENDING}:
        return snap.progress_message
    if status == StageStatus.COMPLETED:
        return "执行完成"
    if status == StageStatus.FAILED:
        return f"执行失败: {error_message}" if error_message else "执行失败"
    if status == StageStatus.SKIPPED:
        return "已跳过"
    return snap.fallback_message
