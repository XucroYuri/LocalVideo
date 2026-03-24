from __future__ import annotations

from typing import Any


def is_audio_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    assets = output_data.get("audio_assets")
    return isinstance(assets, list) and len(assets) > 0


def is_audio_data_usable_strict(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    audio_assets = output_data.get("audio_assets")
    if not isinstance(audio_assets, list) or not audio_assets:
        return False
    for asset in audio_assets:
        if not isinstance(asset, dict):
            return False
        if asset.get("shot_index") is None and asset.get("shot_id") is None:
            return False
    return True


def is_audio_data_usable_with_voice(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    audio_assets = output_data.get("audio_assets")
    if not isinstance(audio_assets, list) or not audio_assets:
        return False
    has_valid_asset = False
    for asset in audio_assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("shot_index") is None and asset.get("shot_id") is None:
            continue
        voice_content = asset.get("voice_content")
        if isinstance(voice_content, str) and voice_content.strip() != "":
            has_valid_asset = True
    return has_valid_asset


def is_video_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    assets = output_data.get("video_assets")
    return isinstance(assets, list) and len(assets) > 0


def is_subtitle_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    subtitle_file_path = output_data.get("subtitle_file_path")
    return isinstance(subtitle_file_path, str) and subtitle_file_path.strip() != ""


def is_compose_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    master_video_path = output_data.get("master_video_path")
    return isinstance(master_video_path, str) and master_video_path.strip() != ""


def is_burn_subtitle_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    burned_video_path = output_data.get("burned_video_path")
    return isinstance(burned_video_path, str) and burned_video_path.strip() != ""


def is_finalize_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    final_video_path = output_data.get("final_video_path")
    return isinstance(final_video_path, str) and final_video_path.strip() != ""


def is_storyboard_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    shots = output_data.get("shots")
    if not isinstance(shots, list) or not shots:
        return False
    for shot in shots:
        if not isinstance(shot, dict):
            return False
        video_prompt = shot.get("video_prompt")
        if not isinstance(video_prompt, str) or video_prompt.strip() == "":
            return False
    return True


def is_shot_data_usable(output_data: Any) -> bool:
    if not isinstance(output_data, dict):
        return False
    shots = output_data.get("shots")
    if not isinstance(shots, list) or not shots:
        return False
    for shot in shots:
        if not isinstance(shot, dict):
            return False
        voice_content = shot.get("voice_content")
        if not isinstance(voice_content, str) or voice_content.strip() == "":
            return False
    return True
