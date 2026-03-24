"""Audio stage shared types, constants, and scheduler adapter."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.stages.common.constants import EMOJI_PATTERN

STORYBOARD_SHOTS_REQUIRED_ERROR = "分镜为空或不可用，请先生成分镜"
CONTENT_REQUIRED_ERROR = "文案内容为空或不可用，请先生成或保存文案"
AUDIO_SPLIT_MODE_BASIC = "basic"
AUDIO_SPLIT_MODE_FASTER_WHISPER = "faster_whisper"


def sanitize_tts_text(text: str) -> str:
    """调用 TTS 前移除 emoji，避免被朗读成语义词。"""
    return EMOJI_PATTERN.sub("", text)


@dataclass
class AudioShotTaskSpec:
    index: int
    key: str
    voice_content: str
    output_path: Path
    skip: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


class AudioShotSchedulerAdapter:
    def __init__(
        self,
        *,
        shot_count: int,
        provider_runtime_fields: Callable[[], dict[str, Any]],
        preserved_output_fields: dict[str, Any] | None = None,
    ) -> None:
        self.shot_count = shot_count
        self.provider_runtime_fields = provider_runtime_fields
        self.preserved_output_fields = dict(preserved_output_fields or {})

    @staticmethod
    def _to_duration(value: Any) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _base_item(spec: AudioShotTaskSpec) -> dict[str, Any]:
        return {
            "shot_index": spec.index,
            "voice_content": spec.voice_content,
            "updated_at": int(time.time()),
        }

    def build_missing_result(self, spec: AudioShotTaskSpec) -> dict[str, Any]:
        base = self._base_item(spec)
        base.update(
            {
                "file_path": None,
                "duration": 0.0,
                "error": "No voice_content",
            }
        )
        return base

    def build_success_result(self, spec: AudioShotTaskSpec, raw_result: Any) -> dict[str, Any]:
        base = self._base_item(spec)
        if isinstance(raw_result, dict):
            base.update(raw_result)
        base["shot_index"] = spec.index
        base["voice_content"] = spec.voice_content
        base["duration"] = self._to_duration(base.get("duration"))
        base.setdefault("updated_at", int(time.time()))
        return base

    def build_error_result(self, spec: AudioShotTaskSpec, error: str) -> dict[str, Any]:
        base = self._base_item(spec)
        base.update(
            {
                "file_path": None,
                "duration": 0.0,
                "error": error,
            }
        )
        return base

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]:
        total_duration = sum(
            self._to_duration(item.get("duration"))
            for item in current_items
            if isinstance(item, dict)
        )
        output = {
            **self.preserved_output_fields,
            "audio_assets": current_items,
            "total_duration": total_duration,
            "shot_count": self.shot_count,
            "generating_shots": generating_shots,
            **self.provider_runtime_fields(),
        }
        if progress_message and generating_shots:
            output["progress_message"] = progress_message
        return output

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_duration = sum(
            self._to_duration(item.get("duration"))
            for item in final_items
            if isinstance(item, dict)
        )
        data = {
            **self.preserved_output_fields,
            "audio_assets": final_items,
            "total_duration": total_duration,
            "shot_count": len(final_items),
            **self.provider_runtime_fields(),
        }
        if failed_items:
            data["failed_items"] = failed_items
        return data

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str:
        details: list[str] = []
        for item in failed_items[:3]:
            item_index = item.get("item_key", item.get("item_index"))
            details.append(f"分镜位{item_index}: {item.get('error', '未知错误')}")
        summary = f"；示例：{'；'.join(details)}" if details else ""
        return f"音频生成存在失败（失败 {len(failed_items)}）{summary}"
