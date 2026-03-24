import logging
import re

NO_TEXT_OVERLAY_REQUIREMENT_ZH = (
    "严禁出现任何字幕、标题条、角标、UI浮层、对话框、贴纸文案或水印说明内容。"
)
NO_TEXT_OVERLAY_REQUIREMENT_EN = (
    "Do not generate subtitles, title bars, corner badges, UI overlays, dialogue bubbles, "
    "sticker text, or watermark annotations."
)
DUO_PODCAST_SPEAKING_REQUIREMENT_MARKERS_ZH = (
    "当前分镜为双人播客固定同框",
    "只有左侧角色在说话",
    "只有右侧角色在说话",
)
DUO_PODCAST_SPEAKING_REQUIREMENT_MARKERS_EN = (
    "This shot is a fixed two-host podcast frame.",
    "Only the left-side role is speaking",
    "Only the right-side role is speaking",
)


def contains_cjk_text(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def has_no_text_overlay_requirement(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    zh_markers = ("严禁出现任何字幕", "标题条", "角标", "ui浮层", "贴纸文案", "水印说明")
    en_markers = (
        "do not generate subtitles",
        "title bars",
        "corner badges",
        "ui overlays",
        "dialogue bubbles",
        "sticker text",
        "watermark annotations",
    )
    return any(marker in normalized for marker in zh_markers) or any(
        marker in normalized for marker in en_markers
    )


def get_no_text_overlay_requirement(prompt: str) -> str:
    if contains_cjk_text(prompt):
        return NO_TEXT_OVERLAY_REQUIREMENT_ZH
    return NO_TEXT_OVERLAY_REQUIREMENT_EN


def has_duo_podcast_speaking_requirement(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    return any(
        marker in normalized for marker in DUO_PODCAST_SPEAKING_REQUIREMENT_MARKERS_ZH
    ) or any(marker in normalized for marker in DUO_PODCAST_SPEAKING_REQUIREMENT_MARKERS_EN)


def get_duo_podcast_speaking_requirement(prompt: str, speaker_side: str | None) -> str:
    normalized_side = str(speaker_side or "").strip().lower()
    if normalized_side not in {"left", "right"}:
        return ""
    is_left = normalized_side == "left"
    if contains_cjk_text(prompt):
        speaking_side = "左侧角色" if is_left else "右侧角色"
        silent_side = "右侧角色" if is_left else "左侧角色"
        return (
            "当前分镜为双人播客固定同框。"
            f"整个片段里{speaking_side}需全程说话，并保持嘴部开合与口型变化。"
            f"{silent_side}保持安静倾听，仅允许自然的微表情、轻微点头或目光反馈，"
            "禁止出现说话口型、明显插话感等任意发声动作。"
        )
    speaking_side = "left-side role" if is_left else "right-side role"
    silent_side = "right-side role" if is_left else "left-side role"
    return (
        "This shot is a fixed two-host podcast frame. "
        f"Throughout the entire shot, the {speaking_side} should keep speaking and maintain visible lip "
        "movement and mouth shape changes. "
        f"The {silent_side} stays silent and listening, with only natural micro-expressions, slight nods, "
        "or eye contact changes. Do not show speaking mouth shapes, interruption cues, or any other "
        "vocalizing action."
    )


def ensure_no_text_overlay_requirement(prompt: str) -> str:
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        return get_no_text_overlay_requirement("")
    if has_no_text_overlay_requirement(normalized_prompt):
        return normalized_prompt
    return f"{normalized_prompt}\n\n{get_no_text_overlay_requirement(normalized_prompt)}"


def ensure_duo_podcast_speaking_requirement(prompt: str, speaker_side: str | None) -> str:
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        return normalized_prompt
    requirement = get_duo_podcast_speaking_requirement(normalized_prompt, speaker_side)
    if not requirement:
        return normalized_prompt
    if has_duo_podcast_speaking_requirement(normalized_prompt):
        return normalized_prompt
    return f"{normalized_prompt}\n\n{requirement}"


def log_full_generation_prompt(logger: logging.Logger, label: str, prompt: str) -> None:
    logger.info("%s\n%s", label, str(prompt or ""))
