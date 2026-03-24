from typing import Any

PROMPT_COMPLEXITY_LABELS = {
    "minimal": "极简",
    "simple": "简单",
    "normal": "正常",
    "detailed": "细节",
    "complex": "复杂",
    "ultra": "极繁",
}

PROMPT_COMPLEXITY_ZH_RANGES = {
    "minimal": "20字以内",
    "simple": "20-50字",
    "normal": "50-150字",
    "detailed": "150-300字",
    "complex": "300-600字",
    "ultra": "600-1000字",
}

PROMPT_COMPLEXITY_EN_RANGES = {
    "minimal": "约 8-16 词",
    "simple": "约 16-35 词",
    "normal": "约 35-110 词",
    "detailed": "约 110-220 词",
    "complex": "约 220-420 词",
    "ultra": "约 420-700 词",
}


def resolve_target_language(value: Any, default: str = "zh") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"zh", "en"}:
        return normalized
    return default


def get_target_language_label(language: str) -> str:
    return "英文" if language == "en" else "中文"


def format_target_language_for_log(value: Any, default: str = "zh") -> str:
    language = resolve_target_language(value, default=default)
    return f"{language}({get_target_language_label(language)})"


def get_unrestricted_language_log_label() -> str:
    return "auto(不限制)"


def resolve_prompt_complexity(value: Any, default: str = "normal") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in PROMPT_COMPLEXITY_LABELS:
        return normalized
    return default


def get_prompt_complexity_label(complexity: str) -> str:
    return PROMPT_COMPLEXITY_LABELS.get(complexity, PROMPT_COMPLEXITY_LABELS["normal"])


def get_prompt_complexity_target_length_label(language: str, complexity: str) -> str:
    if language == "en":
        return PROMPT_COMPLEXITY_EN_RANGES.get(complexity, PROMPT_COMPLEXITY_EN_RANGES["normal"])
    return PROMPT_COMPLEXITY_ZH_RANGES.get(complexity, PROMPT_COMPLEXITY_ZH_RANGES["normal"])


def format_prompt_complexity_for_log(value: Any, default: str = "normal") -> str:
    complexity = resolve_prompt_complexity(value, default=default)
    return f"{complexity}({get_prompt_complexity_label(complexity)})"


def get_reference_description_length_requirement(language: str, complexity: str) -> str:
    zh_range = PROMPT_COMPLEXITY_ZH_RANGES.get(complexity, PROMPT_COMPLEXITY_ZH_RANGES["normal"])
    label = get_prompt_complexity_label(complexity)
    if language == "en":
        en_range = PROMPT_COMPLEXITY_EN_RANGES.get(
            complexity, PROMPT_COMPLEXITY_EN_RANGES["normal"]
        )
        return (
            f"目标复杂度为“{label}”：每个参考 description 使用英文，长度建议 {en_range} "
            f"（对应中文约 {zh_range} 的信息量）。"
        )
    return f"目标复杂度为“{label}”：每个参考 description 长度建议 {zh_range}。"


def get_video_prompt_length_requirement(language: str, complexity: str) -> str:
    zh_range = PROMPT_COMPLEXITY_ZH_RANGES.get(complexity, PROMPT_COMPLEXITY_ZH_RANGES["normal"])
    label = get_prompt_complexity_label(complexity)
    if language == "en":
        en_range = PROMPT_COMPLEXITY_EN_RANGES.get(
            complexity, PROMPT_COMPLEXITY_EN_RANGES["normal"]
        )
        return (
            f"目标复杂度为“{label}”：每条 video_prompt 使用英文，长度建议 {en_range} "
            f"（对应中文约 {zh_range} 的信息量）。"
        )
    return f"目标复杂度为“{label}”：每条 video_prompt 长度建议 {zh_range}。"


def get_first_frame_prompt_length_requirement(language: str, complexity: str) -> str:
    zh_range = PROMPT_COMPLEXITY_ZH_RANGES.get(complexity, PROMPT_COMPLEXITY_ZH_RANGES["normal"])
    label = get_prompt_complexity_label(complexity)
    if language == "en":
        en_range = PROMPT_COMPLEXITY_EN_RANGES.get(
            complexity, PROMPT_COMPLEXITY_EN_RANGES["normal"]
        )
        return (
            f"目标复杂度为“{label}”：每条 first_frame_prompt 使用英文，长度建议 {en_range} "
            f"（对应中文约 {zh_range} 的信息量）。"
        )
    return f"目标复杂度为“{label}”：每条 first_frame_prompt 长度建议 {zh_range}。"


def get_vision_description_length_requirement(language: str, complexity: str) -> str:
    zh_range = PROMPT_COMPLEXITY_ZH_RANGES.get(complexity, PROMPT_COMPLEXITY_ZH_RANGES["normal"])
    label = get_prompt_complexity_label(complexity)
    if language == "en":
        en_range = PROMPT_COMPLEXITY_EN_RANGES.get(
            complexity, PROMPT_COMPLEXITY_EN_RANGES["normal"]
        )
        return (
            f"Target complexity is '{label}': keep the description around {en_range} "
            f"(roughly equivalent to Chinese {zh_range} information density)."
        )
    return f"目标复杂度为“{label}”：描述长度建议 {zh_range}。"


def get_reference_description_requirement(language: str) -> str:
    if language == "en":
        return """外观描述必须使用英文，尽量覆盖以下可见要素（按实际适用）：
   - 主体类型（人物 / 生物 / 物体 / 标识 / 场景元素）
   - 外形结构与比例
   - 关键视觉特征（颜色、材质、纹理、图案）
   - 可见配件或标识细节
   - 姿态、朝向或状态（如适用）"""
    return """外观描述必须使用中文，尽量覆盖以下可见要素（按实际适用）：
   - 主体类型（人物 / 生物 / 物体 / 标识 / 场景元素）
   - 外形结构与比例
   - 关键视觉特征（颜色、材质、纹理、图案）
   - 可见配件或标识细节
   - 姿态、朝向或状态（如适用）"""


def get_reference_description_example(language: str) -> str:
    if language == "en":
        return "[detailed English appearance description]..."
    return "[详细中文外观描述]..."


def get_video_prompt_example(language: str, index: int) -> str:
    if language == "en":
        return f"English video description for shot {index}..."
    return f"第{index}段中文视频描述..."


def get_first_frame_prompt_example(language: str) -> str:
    if language == "en":
        return "English first frame description..."
    return "中文首帧构图描述..."


__all__ = [
    "PROMPT_COMPLEXITY_EN_RANGES",
    "PROMPT_COMPLEXITY_LABELS",
    "PROMPT_COMPLEXITY_ZH_RANGES",
    "format_prompt_complexity_for_log",
    "format_target_language_for_log",
    "get_first_frame_prompt_example",
    "get_first_frame_prompt_length_requirement",
    "get_prompt_complexity_label",
    "get_prompt_complexity_target_length_label",
    "get_reference_description_example",
    "get_reference_description_length_requirement",
    "get_reference_description_requirement",
    "get_target_language_label",
    "get_unrestricted_language_log_label",
    "get_video_prompt_example",
    "get_video_prompt_length_requirement",
    "get_vision_description_length_requirement",
    "resolve_prompt_complexity",
    "resolve_target_language",
]
