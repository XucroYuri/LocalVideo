"""Video stage types, constants, scheduler adapter, and model capability helpers."""

from __future__ import annotations

import time as time_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.providers.video_capabilities import (
    get_max_reference_images,
)
from app.providers.video_capabilities import (
    supports_combined_reference as capability_supports_combined_reference,
)
from app.providers.video_capabilities import (
    supports_last_frame as capability_supports_last_frame,
)
from app.providers.video_capabilities import (
    supports_reference_image as capability_supports_reference_image,
)

# ---------------------------------------------------------------------------
# Error message constants
# ---------------------------------------------------------------------------

VIDEO_PROMPT_REQUIRED_ERROR = "视频描述为空或不可用，请先生成视频描述"
AUDIO_DATA_REQUIRED_ERROR = "音频数据为空或不可用，请先生成音频"
FIRST_FRAME_DATA_REQUIRED_ERROR = "已启用首帧图参考，但首帧图资源不完整，请先生成首帧图"
SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR = (
    "一镜到底模式下缺少上一个分镜位视频，无法为当前分镜位提取首帧"
)
REFERENCE_IMAGE_DATA_REQUIRED_ERROR = "已启用参考图转视频，但参考图资源不完整，请先生成参考图"
REFERENCE_IMAGE_UNSUPPORTED_ERROR = "当前视频模型不支持参考图转视频"
COMBINED_REFERENCE_UNSUPPORTED_ERROR = "当前视频模型不支持同时启用首帧图参考和参考图转视频"

# ---------------------------------------------------------------------------
# VideoTaskSpec
# ---------------------------------------------------------------------------


@dataclass
class VideoTaskSpec:
    index: int
    key: str
    video_prompt: str
    duration: float
    output_path: Path
    first_frame: Path | None = None
    last_frame: Path | None = None
    reference_images: list[Path] | None = None
    skip: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# VideoSchedulerAdapter
# ---------------------------------------------------------------------------


class VideoSchedulerAdapter:
    def __init__(self, shot_count: int, provider_name: str):
        self.shot_count = shot_count
        self.provider_name = provider_name

    @staticmethod
    def _resolve_stage_runtime_provider(
        items: list[dict[str, Any]],
        fallback_provider_name: str,
    ) -> str:
        providers = {
            str(item.get("runtime_provider") or item.get("video_provider") or "").strip()
            for item in items
            if isinstance(item, dict)
        }
        providers.discard("")
        if len(providers) == 1:
            return next(iter(providers))
        if len(providers) > 1:
            return "mixed"
        return fallback_provider_name

    def build_missing_result(self, spec: VideoTaskSpec) -> dict[str, Any]:
        return {
            "shot_index": spec.index,
            "file_path": None,
            "error": "No video prompt",
        }

    @staticmethod
    def _resolve_existing_asset(spec: VideoTaskSpec) -> dict[str, Any] | None:
        payload = spec.payload if isinstance(spec.payload, dict) else {}
        existing = payload.get("existing_video_asset")
        if not isinstance(existing, dict):
            return None
        file_path = str(existing.get("file_path") or "").strip()
        if not file_path:
            return None
        output = dict(existing)
        output["shot_index"] = spec.index
        output.setdefault("updated_at", int(time_module.time()))
        return output

    def build_success_result(self, spec: VideoTaskSpec, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            existing_asset = self._resolve_existing_asset(spec)
            if existing_asset is not None:
                return existing_asset
            return {
                "shot_index": spec.index,
                "file_path": None,
                "error": "Invalid video result",
            }
        output = dict(raw_result)
        output["shot_index"] = spec.index
        file_path = str(output.get("file_path") or "").strip()
        if not file_path:
            existing_asset = self._resolve_existing_asset(spec)
            if existing_asset is not None:
                return existing_asset
        output.setdefault("updated_at", int(time_module.time()))
        return output

    def build_error_result(self, spec: VideoTaskSpec, error: str) -> dict[str, Any]:
        existing_asset = self._resolve_existing_asset(spec)
        if existing_asset is not None:
            return existing_asset
        return {
            "shot_index": spec.index,
            "file_path": None,
            "error": error,
        }

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]:
        runtime_provider = self._resolve_stage_runtime_provider(current_items, provider_name)
        output = {
            "video_assets": current_items,
            "video_count": self.shot_count,
            "generating_shots": generating_shots,
            "runtime_provider": runtime_provider,
            "video_provider": runtime_provider,
        }
        if progress_message and generating_shots:
            output["progress_message"] = progress_message
        return output

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        runtime_provider = self._resolve_stage_runtime_provider(final_items, self.provider_name)
        data = {
            "video_assets": final_items,
            "video_count": len(final_items),
            "runtime_provider": runtime_provider,
            "video_provider": runtime_provider,
        }
        if failed_items:
            data["failed_items"] = failed_items
        return data

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str:
        details: list[str] = []
        for item in failed_items[:3]:
            item_index = item.get("item_key")
            if item_index is None or item_index == "":
                item_index = item.get("item_index")
            details.append(f"分镜位{item_index}: {item.get('error', '未知错误')}")
        summary = f"；示例：{'；'.join(details)}" if details else ""
        return f"视频生成存在失败（失败 {len(failed_items)}）{summary}"


# ---------------------------------------------------------------------------
# Model capability helper functions
# ---------------------------------------------------------------------------


def normalize_model_key(model: str | None) -> str:
    return str(model or "").strip().lower()


def is_seedance_reference_model(normalized_model: str) -> bool:
    return "seedance-1-0-lite-i2v" in str(normalized_model or "")


def supports_reference_images(provider_name: str, model: str) -> bool:
    return capability_supports_reference_image(provider_name, model, None)


def supports_combined_references(provider_name: str, model: str) -> bool:
    return capability_supports_combined_reference(provider_name, model, None)


def max_reference_images_per_shot(provider_name: str, model: str) -> int:
    return get_max_reference_images(provider_name, model, None)


def supports_last_frame(provider_name: str, model: str) -> bool:
    return capability_supports_last_frame(provider_name, model, None)


def dedupe_reasons(reasons: list[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def append_last_frame_lock_instruction(prompt: str) -> str:
    text = str(prompt or "").strip()
    lower_text = text.lower()
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    cn_rule = (
        "尾帧收敛规则：最后0.5-1秒需要逐帧收敛到提供的尾帧参考图，"
        "结束时两人回到初始姿态并自然定格。"
    )
    en_rule = (
        "Tail convergence rule: during the final 0.5-1.0 seconds, frames should progressively "
        "converge to the provided last-frame reference image; by the end, both characters return "
        "to their initial posture and hold a natural freeze."
    )

    if has_cjk:
        if "尾帧收敛规则" in text or "逐帧收敛到提供的尾帧参考图" in text:
            return text
        if not text:
            return cn_rule
        return f"{text} {cn_rule}"

    if "tail convergence rule" in lower_text or "last-frame reference image" in lower_text:
        return text
    if not text:
        return en_rule
    return f"{text} {en_rule}"
