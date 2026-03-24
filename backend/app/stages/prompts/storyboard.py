"""Storyboard stage prompt builders."""

from __future__ import annotations

from typing import Any

from .common import (
    get_prompt_complexity_label,
    get_target_language_label,
    get_video_prompt_example,
    get_video_prompt_length_requirement,
    resolve_prompt_complexity,
    resolve_target_language,
)

STORYBOARD_STANDARD_MODE_GUIDANCE = """模式风格要求：
- 画面应贴近信息型口播短视频，强调叙事推进、信息节点和主体可辨识性。
- 若涉及真实人物，不要直接把真实姓名写进 video_prompt，改用身份描述或参考主体描述。
- 每个分镜必须是可单独生成的视频片段，不能依赖前后镜头补全信息。
- 优先让主体、环境或关键物件产生可见动作与状态变化，不要只用推拉摇移制造“假动感”。
- 若画面里存在人物，优先补足表情、姿态、手势、视线、步态或交互反馈；镜头运动只作为辅助，不应成为唯一变化源。"""

STORYBOARD_DUO_PODCAST_MODE_GUIDANCE = """模式风格要求：
- 这是双人播客一镜到底语境下的分镜规划，重点是两位讲述者的动作层变化、互动节奏与语义呼应。
- video_prompt 不要堆砌固定规则文本，例如固定机位、固定场景、座位方向、禁字幕等；这些由系统处理。
- 动作描写应突出当前发言者，另一位只保留克制、自然的辅助动作。
- 角色称呼统一使用“左侧角色/右侧角色”等位置化称呼，避免真实人名。
- 这是固定场景的一镜到底表达，不要主动设计推拉摇移、环绕、跟拍、手持漂移等明显镜头运动。
- 优先输出两位讲述者在表情、手势、身体重心、视线交换、停顿反应上的真实动作层变化。"""

STORYBOARD_DIALOGUE_SCRIPT_MODE_GUIDANCE = """模式风格要求：
- 这是台词剧本分镜，必须体现剧情推进、冲突强弱、角色目标与转折感。
- 若该段更像画外音/旁白，video_prompt 可偏向环境、物件、空间调度与情境状态。
- 若该段是角色发言，当前说话角色必须在镜头中可辨识，并给出与语义匹配的表情、姿态与动作反馈。
- 冲突升级段允许更强镜头变化，转折段需要明确视觉锚点。
- 优先写人物行为、对抗动作、情绪反应、环境反馈或物件变化，不要只写镜头推拉摇移而缺少戏剧动作。"""

STORYBOARD_REGENERATE_STANDARD_GUIDANCE = """重生成要求：
- 只重写这个分镜的 video_prompt 与 video_reference_slots。
- voice_content、speaker_id、speaker_name 必须保持不变。
- 生成的 video_prompt 必须延续当前模式应有的视频描述风格。"""

STORYBOARD_REGENERATE_DUO_PODCAST_GUIDANCE = """重生成要求：
- 只重写这个分镜的动作层 video_prompt 与 video_reference_slots。
- 不要重复固定场景/固定机位/座位方向等系统规则。
- voice_content、speaker_id、speaker_name 必须保持不变。"""

STORYBOARD_REGENERATE_DIALOGUE_SCRIPT_GUIDANCE = """重生成要求：
- 只重写这个分镜的 video_prompt 与 video_reference_slots。
- 若该分镜是角色发言，当前说话角色需保持可辨识；若是旁白语义，可偏向环境叙事。
- voice_content、speaker_id、speaker_name 必须保持不变。"""

SMART_MERGE_STANDARD_MODE_GUIDANCE = """合并风格要求：
- 尽量把语义连续、主体连续、机位连续的段落合并，以减少调用次数并增强连续性。
- 合并后的 video_prompt 应覆盖整段，不是把原 video_prompt 机械拼接。"""

SMART_MERGE_DUO_PODCAST_MODE_GUIDANCE = """合并风格要求：
- 优先合并同一位讲述者连续输出、情绪动作连续的段落。
- 若分开发言更能保持播客对话节奏和镜头稳定性，就不要为了减少数量而强行合并。
- 合并后的 video_prompt 仍然只描述动作层变化，不重复固定系统规则。"""

SMART_MERGE_DIALOGUE_SCRIPT_MODE_GUIDANCE = """合并风格要求：
- 优先合并同一角色连续推进、同一场次/同一冲突节拍内的段落。
- 若独立保留更有利于冲突、转折或角色目标表达，就不要强行合并。
- 合并后的 video_prompt 需要保留剧情推进感，而不是把多个独立戏点压扁。"""

CONDITIONAL_SMART_MERGE_REFERENCE_RULE = """参考约束（仅本次任务生效）：
1. 在候选合并段内，任意前后相邻两个原分镜中，后一个原分镜的参考集合只能与前一个相同或更少，不能新增参考。
2. 如果后一个原分镜出现了新的参考，就不要把这两个原分镜放进同一合并段，因为未在首帧出现的参考无法保证一致性。"""


def _resolve_storyboard_mode_family(script_mode: str) -> str:
    normalized = str(script_mode or "").strip().lower()
    if normalized == "duo_podcast":
        return "duo_podcast"
    if normalized == "dialogue_script":
        return "dialogue_script"
    return "standard"


def _build_mode_guidance(script_mode: str, *, smart_merge: bool = False) -> str:
    mode_family = _resolve_storyboard_mode_family(script_mode)
    if smart_merge:
        if mode_family == "duo_podcast":
            return SMART_MERGE_DUO_PODCAST_MODE_GUIDANCE
        if mode_family == "dialogue_script":
            return SMART_MERGE_DIALOGUE_SCRIPT_MODE_GUIDANCE
        return SMART_MERGE_STANDARD_MODE_GUIDANCE

    if mode_family == "duo_podcast":
        return STORYBOARD_DUO_PODCAST_MODE_GUIDANCE
    if mode_family == "dialogue_script":
        return STORYBOARD_DIALOGUE_SCRIPT_MODE_GUIDANCE
    return STORYBOARD_STANDARD_MODE_GUIDANCE


def _build_regenerate_guidance(script_mode: str) -> str:
    mode_family = _resolve_storyboard_mode_family(script_mode)
    if mode_family == "duo_podcast":
        return STORYBOARD_REGENERATE_DUO_PODCAST_GUIDANCE
    if mode_family == "dialogue_script":
        return STORYBOARD_REGENERATE_DIALOGUE_SCRIPT_GUIDANCE
    return STORYBOARD_REGENERATE_STANDARD_GUIDANCE


def _build_prompt_craft_requirement(script_mode: str) -> str:
    mode_family = _resolve_storyboard_mode_family(script_mode)
    if mode_family == "duo_podcast":
        return (
            "使用更专业的双人播客动作层提示词技巧：明确两位角色在固定同框中的"
            "表情、手势、姿态、视线交换、身体重心、停顿节奏、局部构图重心、布光层次"
            "与前后景空间关系；不要主动引入推拉摇移、环绕、跟拍等镜头运动。"
        )
    return (
        "使用更专业的视频提示词技巧：明确构图（近景/中景/远景）、机位"
        "（俯仰/跟拍/环绕/推拉摇移）、光照（主光/轮廓光/环境光）、材质与动效"
        "（粒子/雾气/反射/景深）、色彩脚本（主色与对比色）。"
    )


def _build_motion_balance_requirement(script_mode: str) -> str:
    mode_family = _resolve_storyboard_mode_family(script_mode)
    if mode_family == "duo_podcast":
        return (
            "不要把镜头运动当成变化来源；应在固定同框、一镜到底前提下，通过人物动作、"
            "互动节奏、视线关系、表情转折和局部构图重心变化建立动感。"
        )
    return (
        "不要让镜头运动成为唯一变化来源；如果写了推拉摇移，仍需明确主体动作、表情、"
        "姿态、物件变化或场景内运动。"
    )


def _build_shot_variation_requirement(script_mode: str) -> str:
    mode_family = _resolve_storyboard_mode_family(script_mode)
    if mode_family == "duo_podcast":
        return (
            "在固定播客空间与整体风格连贯的前提下，通过当前发言者切换、互动节奏、"
            "表情转折、手势变化、视线交换和局部构图重心变化制造区分，避免每条都只是同一种坐姿和同一类手势。"
        )
    return "在“整体风格连贯”的前提下保持分镜差异化，避免所有分镜同构同调。"


def resolve_storyboard_prompt_config(input_data: dict[str, Any] | None) -> dict[str, str]:
    target_language = resolve_target_language((input_data or {}).get("target_language"))
    prompt_complexity = resolve_prompt_complexity((input_data or {}).get("prompt_complexity"))
    return {
        "target_language": target_language,
        "target_language_label": get_target_language_label(target_language),
        "prompt_complexity": prompt_complexity,
        "prompt_complexity_label": get_prompt_complexity_label(prompt_complexity),
        "video_prompt_length_requirement": get_video_prompt_length_requirement(
            target_language,
            prompt_complexity,
        ),
    }


def build_storyboard_prompt(
    *,
    script_mode: str,
    title: str,
    source_display: str,
    reference_info: str,
    shot_plan_note: str,
    target_language: str,
    target_language_label: str,
    prompt_complexity: str,
    prompt_complexity_label: str,
    video_prompt_length_requirement: str,
) -> str:
    mode_guidance = _build_mode_guidance(script_mode)
    craft_requirement = _build_prompt_craft_requirement(script_mode)
    motion_balance_requirement = _build_motion_balance_requirement(script_mode)
    shot_variation_requirement = _build_shot_variation_requirement(script_mode)
    return f"""项目标题：{title or "未命名项目"}
创作模式：{script_mode}
视频描述目标语言：{target_language}（{target_language_label}）
视频描述目标复杂度：{prompt_complexity}（{prompt_complexity_label}）

原始文案：
{source_display}

参考信息：
{reference_info}

镜头规划指引：
{shot_plan_note}

{mode_guidance}

通用要求：
1. 所有 shots 的 voice_content 拼接后必须与原始文案完全一致。
2. 分镜应按叙事顺序输出，shot_index 从 0 开始连续递增。
3. video_prompt 必须使用{target_language_label}描述。
4. {video_prompt_length_requirement}
5. video_reference_slots 为空时返回 []。
6. 如果不同主体在镜头中先后出现且可见集合变化，必须拆成多个分镜。
7. 每个分镜的 video_prompt 必须可直接单独喂给视频模型使用。
8. 每条都要有完整闭环：主体 + 场景 + 关键动作 + 镜头语言 + 光线/色彩 + 氛围风格。
9. 与口播语义严格对应，避免空泛词和套话；避免主体只有静止站立/静坐，若语义允许应加入可见动作、交互或环境反馈。
10. {shot_variation_requirement}
11. {craft_requirement}
12. {motion_balance_requirement}
13. 严禁出现跨分镜依赖表达，例如“承接上一镜、然后切到、镜头转向下一段”等。
14. 严禁在画面中生成字幕、文字叠加、标题条、角标、UI浮层或水印说明。

请规划分镜并返回 JSON：
{{
  "shots": [
    {{
      "shot_index": 0,
      "voice_content": "直接复制原文中的一段",
      "speaker_id": "ref_01",
      "speaker_name": "讲述者",
      "video_prompt": "{get_video_prompt_example(target_language, 1)}",
      "video_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}]
    }}
  ]
}}

不要输出任何解释文本，只输出 JSON。"""


def build_storyboard_regenerate_prompt(
    *,
    script_mode: str,
    title: str,
    reference_info: str,
    shot: dict[str, Any],
    only_shot_index: int,
    target_language: str,
    target_language_label: str,
    prompt_complexity: str,
    prompt_complexity_label: str,
    video_prompt_length_requirement: str,
) -> str:
    regenerate_guidance = _build_regenerate_guidance(script_mode)
    motion_balance_requirement = _build_motion_balance_requirement(script_mode)
    return f"""项目标题：{title or "未命名项目"}
创作模式：{script_mode}
视频描述目标语言：{target_language}（{target_language_label}）
视频描述目标复杂度：{prompt_complexity}（{prompt_complexity_label}）
当前任务：仅重生成第 {only_shot_index + 1} 个分镜的视频描述与参考，不要改写 voice_content。

参考信息：
{reference_info}

目标分镜：
- shot_index={only_shot_index}
- speaker={shot.get("speaker_name") or shot.get("speaker_id") or "ref_01"}
- voice_content={shot.get("voice_content") or ""}

{regenerate_guidance}

通用要求：
1. video_prompt 必须使用{target_language_label}描述。
2. {video_prompt_length_requirement}
3. 每个分镜的 video_prompt 必须可直接单独喂给视频模型使用。
4. 重生成后的 video_prompt 仍需形成完整闭环：主体 + 场景 + 关键动作 + 镜头语言 + 光线/色彩 + 氛围风格。
5. 优先补足主体动作、表情、姿态、视线或物件/环境反馈。{motion_balance_requirement}
6. 严禁出现跨分镜依赖表达，例如“承接上一镜、然后切到、镜头转向下一段”等。
7. 严禁在画面中生成字幕、文字叠加、标题条、角标、UI浮层或水印说明。

请返回 JSON：
{{
  "shots": [
    {{
      "shot_index": {only_shot_index},
      "voice_content": "必须与输入完全一致",
      "speaker_id": "{shot.get("speaker_id") or "ref_01"}",
      "speaker_name": "{shot.get("speaker_name") or shot.get("speaker_id") or "ref_01"}",
      "video_prompt": "{get_video_prompt_example(target_language, 1)}",
      "video_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}]
    }}
  ]
}}

不要输出任何解释文本，只输出 JSON。"""


def build_storyboard_smart_merge_prompt(
    *,
    script_mode: str,
    title: str,
    reference_info: str,
    shots_display: str,
    total_duration_seconds: float,
    shot_count: int,
    average_duration_seconds: float,
    minimum_shot_count: int,
    recommended_min_shot_count: int,
    recommended_max_shot_count: int,
    video_provider: str,
    video_model: str,
    video_mode: str,
    max_duration_seconds: float,
    use_first_frame_ref: bool,
    use_reference_image_ref: bool,
    target_language: str,
    target_language_label: str,
    prompt_complexity: str,
    prompt_complexity_label: str,
    video_prompt_length_requirement: str,
) -> str:
    del video_provider, video_model, video_mode, prompt_complexity, prompt_complexity_label
    mode_guidance = _build_mode_guidance(script_mode, smart_merge=True)
    conditional_reference_rule = ""
    if use_first_frame_ref and not use_reference_image_ref:
        conditional_reference_rule = f"\n{CONDITIONAL_SMART_MERGE_REFERENCE_RULE}\n"

    return f"""项目标题：{title or "未命名项目"}
当前任务：智能合并当前分镜，在约束下尽可能减少分镜数量，同时保证生成一致性。
当前单镜头合并时长上限：{max_duration_seconds:.3f} 秒

可用参考信息：
{reference_info}

当前分镜列表：
{shots_display}

{mode_guidance}

硬约束：
1. 只能合并连续分镜，不能重排。
2. 每个合并后的分镜只能来自同一 speaker_id 的连续分镜。
3. 合并后的 voice_content 必须等于 source_shot_indices 对应原分镜 voice_content 的连续拼接，不能改写。
4. 合并后的单个分镜总时长不能超过 {max_duration_seconds:.3f} 秒。
5. 当前视频总时长约 {total_duration_seconds:.3f} 秒，镜头数 {shot_count} 个，平均每段时长约 {average_duration_seconds:.3f} 秒；按照每个镜头不超过 {max_duration_seconds:.3f} 秒计算，最大压缩到 {minimum_shot_count} 个，比较合理的区间是 {recommended_min_shot_count}-{recommended_max_shot_count} 个。
6. video_prompt 必须使用{target_language_label}描述。
7. {video_prompt_length_requirement}
8. video_reference_slots 只能从可用参考中选择。
9. 每个合并后的 video_prompt 必须可直接单独喂给视频模型使用。
10. 严禁在画面中生成字幕、文字叠加、标题条、角标、UI浮层或水印说明。{conditional_reference_rule}

质量约束：
1. 优先合并明显连续、主体/机位/叙事连续的段落。
2. 如果保持独立或向后合并更利于一致性，不要强行向前合并。
3. 合并后的 video_prompt 要覆盖整个合并段，而不是机械拼接原描述。
4. 如果一个合并分镜包含多个原分镜阶段，video_prompt 必须明确写出段内推进，优先使用“镜头1：… 镜头2：… 镜头3：…”的结构化表达，不能把多个阶段压成一个笼统静态镜头总结。

请只输出 JSON：
{{
  "shots": [
    {{
      "shot_index": 0,
      "source_shot_indices": [0, 1],
      "voice_content": "原分镜文案直接拼接后的结果",
      "speaker_id": "ref_01",
      "speaker_name": "讲述者",
      "video_prompt": "镜头1：{get_video_prompt_example(target_language, 1)} 镜头2：延续同一主体与场景，明确第二阶段动作、表情、机位或构图变化。",
      "video_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}]
    }}
  ]
}}

不要输出任何解释文本，只输出 JSON。"""


def build_storyboard_smart_merge_repair_prompt(
    *,
    script_mode: str,
    title: str,
    reference_info: str,
    issue_message: str,
    current_window_display: str,
    source_window_display: str,
    max_duration_seconds: float,
    target_language: str,
    target_language_label: str,
    prompt_complexity: str,
    prompt_complexity_label: str,
    video_prompt_length_requirement: str,
) -> str:
    del prompt_complexity, prompt_complexity_label
    mode_guidance = _build_mode_guidance(script_mode, smart_merge=True)
    return f"""项目标题：{title or "未命名项目"}
当前任务：修复智能合并结果中的局部错误，只能重写给定修复窗口，不要改动窗口之外的分镜。
当前问题：
{issue_message}

可用参考信息：
{reference_info}

原始分镜窗口（只能基于这些原分镜重组，不能引用窗口外 source_shot_indices）：
{source_window_display}

当前合并结果窗口（这是待修复的局部结果）：
{current_window_display}

{mode_guidance}

硬约束：
1. 只能输出“修复后的局部 merged shots”，不要输出窗口外分镜。
2. source_shot_indices 必须来自“原始分镜窗口”，且每条必须是连续区间。
3. 修复后的局部结果必须完整覆盖原始分镜窗口，不得缺漏、重叠、倒序或跨窗引用。
4. 每个合并后的分镜只能来自同一 speaker_id 的连续分镜。
5. voice_content 必须等于对应 source_shot_indices 原分镜 voice_content 的连续拼接，不能改写。
6. 每个合并后的单个分镜总时长不能超过 {max_duration_seconds:.3f} 秒。
7. video_prompt 必须使用{target_language_label}描述。
8. {video_prompt_length_requirement}
9. video_reference_slots 只能从可用参考中选择。
10. 每个合并后的 video_prompt 必须可直接单独喂给视频模型使用。
11. 严禁在画面中生成字幕、文字叠加、标题条、角标、UI浮层或水印说明。

输出要求：
1. 优先在最小改动范围内修复当前问题，不要无故改变窗口内原本合法的切分。
2. 如果需要拆分问题分镜，可以拆成多个更小的 merged shots。
3. 如果某条 video_prompt 需要重写，请写成可直接使用的完整中文提示词，不要写解释。
4. 只输出 JSON。

请返回 JSON：
{{
  "shots": [
    {{
      "shot_index": 0,
      "source_shot_indices": [0],
      "voice_content": "对应原始分镜文案",
      "speaker_id": "ref_01",
      "speaker_name": "讲述者",
      "video_prompt": "{get_video_prompt_example(target_language, 1)}",
      "video_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}]
    }}
  ]
}}

不要输出任何解释文本，只输出 JSON。"""


__all__ = [
    "build_storyboard_prompt",
    "build_storyboard_regenerate_prompt",
    "build_storyboard_smart_merge_repair_prompt",
    "build_storyboard_smart_merge_prompt",
    "resolve_storyboard_prompt_config",
]
