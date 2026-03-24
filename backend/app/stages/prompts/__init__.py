# 新闻事实研究（生成信息）
from .common import (
    PROMPT_COMPLEXITY_EN_RANGES,
    PROMPT_COMPLEXITY_LABELS,
    PROMPT_COMPLEXITY_ZH_RANGES,
    format_prompt_complexity_for_log,
    format_target_language_for_log,
    get_first_frame_prompt_example,
    get_first_frame_prompt_length_requirement,
    get_prompt_complexity_label,
    get_reference_description_example,
    get_reference_description_length_requirement,
    get_reference_description_requirement,
    get_target_language_label,
    get_unrestricted_language_log_label,
    get_video_prompt_example,
    get_video_prompt_length_requirement,
    get_vision_description_length_requirement,
    resolve_prompt_complexity,
    resolve_target_language,
)
from .custom import (
    CONTENT_CUSTOM_USER,
)
from .dialogue_script import (
    CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER,
    CONTENT_DIALOGUE_SCRIPT_USER,
    FIRST_FRAME_BATCH_DIALOGUE_SCRIPT_USER,
    VIDEO_PROMPT_DIALOGUE_SCRIPT_USER,
)
from .duo_podcast import (
    CONTENT_CUSTOM_DUO_USER,
    CONTENT_DIALOGUE_DUO_USER,
    DUO_PODCAST_STYLE_DESCRIPTIONS,
    FIRST_FRAME_BATCH_DUO_SYSTEM,
    FIRST_FRAME_BATCH_DUO_USER,
    VIDEO_PROMPT_DUO_PODCAST_SINGLE_TAKE_USER,
)
from .single import (
    CONTENT_CUSTOM_SINGLE_USER,
    CONTENT_USER,
    STYLE_DESCRIPTIONS,
)
from .storyboard import (
    build_storyboard_prompt,
    build_storyboard_regenerate_prompt,
    build_storyboard_smart_merge_prompt,
    build_storyboard_smart_merge_repair_prompt,
    resolve_storyboard_prompt_config,
)

CONTENT_SYSTEM = """你是一个专业的短视频脚本编剧，擅长创作多题材、可视化表达强的短视频脚本。"""

VIDEO_PROMPT_SYSTEM = """你是一个专业的短视频导演与提示词工程师。
你的输出将被直接作为下游视频生成模型的输入提示词，必须严格可执行、可单独使用。"""

TITLE_USER = """请为以下短视频口播文案生成一个吸引眼球的标题。

文案内容：
{content}

要求：
1. 标题要简短有力，10-20字为宜
2. 能概括核心观点或事件
3. 有一定的吸引力和话题性

请只输出标题，不要输出其他任何内容。"""


VIDEO_PROMPT_COMMON_STANDARD_USER = """请为以下分镜脚本生成{target_language_name}视频描述。

生成范围：
{generation_scope}

视频生成参数（请据此控制画面设计）：
{video_spec_summary}

时长控制信息（请据此控制镜头密度与信息量）：
{duration_guidance}

分镜内容：
{shots_display}

可用参考信息（按需选用，不可编造ID）：
{reference_info}

硬性要求（必须全部满足）：
1. 每条 video_prompt 使用{target_language_name}描述，且可被“单独拿出去”直接生成视频。
2. 严禁出现跨分镜依赖表达：例如“无缝转场、承接上一镜、接上个镜头、然后切到”等开场写法。
3. 每条都要有完整闭环：主体 + 场景 + 关键动作 + 镜头语言 + 光线/色彩 + 氛围风格。
4. 与口播语义严格对应，避免空泛词和套话；避免真实人名，使用身份/参考主体描述。
5. 在“整体风格连贯”的前提下保持分镜差异化，避免所有分镜同构同调。
6. 镜头组织必须遵循后文“附加硬性要求（镜头组织）”。
7. 使用更专业的视频提示词技巧：明确构图（近景/中景/远景）、机位（俯仰/跟拍/环绕/推拉摇移）、光照（主光/轮廓光/环境光）、材质与动效（粒子/雾气/反射/景深）、色彩脚本（主色与对比色）。
8. {video_prompt_length_requirement}
9. 严禁生成任何字幕、文字叠加、标题条、角标、UI浮层或水印说明文本（画面中不得出现可读文字）。
10. 每个分镜都必须返回 video_reference_slots（数组），用于明确顺序与名称；若该分镜不需要参考图，返回空数组 []。
11. video_reference_slots 元素格式固定为 {{"order": 1, "id": "ref_01", "name": "参考名称"}}；id 只能从“可用参考信息”里选，禁止编造。

请以JSON格式输出：
{{
  "video_prompts": [
    {{
      "shot_index": 0,
      "video_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}],
      "video_prompt": "{video_prompt_example_1}"
    }},
    {{
      "shot_index": 1,
      "video_reference_slots": [],
      "video_prompt": "{video_prompt_example_2}"
    }}
  ]
}}"""

FIRST_FRAME_BATCH_COMMON_USER = """请为以下分镜脚本设计首帧图像的构图描述。

生成范围：
{generation_scope}

全部分镜内容：
{all_shots}

参考信息：
{references}

要求：
1. 用{target_language_name}描述每个首帧构图。
2. 必须严格对齐对应 video_prompt 的开场首帧（第一个可见画面，t=0~1s）。
3. 如果 video_prompt 里有“then/after/转场后”的后续内容，禁止把这些后续内容写进首帧。
4. 从全局视角设计，确保分镜之间视觉连贯但有变化。
5. 包含场景、人物位置、动作、表情、光线等，但动作应是“首帧瞬间”而非连续动作链。
6. {first_frame_prompt_length_requirement}
7. 每个分镜都必须输出 first_frame_reference_slots（数组），不得省略；若该分镜不需要参考图则输出 []。
8. first_frame_reference_slots 元素格式固定为 {{"order": 1, "id": "ref_01", "name": "参考名称"}}；id 只能从“参考信息”中选择，禁止编造。

请以JSON格式输出：
{{
  "frames": [
    {{
      "shot_index": 0,
      "first_frame_reference_slots": [{{"order": 1, "id": "ref_01", "name": "参考名称"}}],
      "first_frame_prompt": "{first_frame_prompt_example}"
    }},
    ...
  ]
}}"""

__all__ = [
    "CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER",
    "CONTENT_CUSTOM_DUO_USER",
    "CONTENT_CUSTOM_SINGLE_USER",
    "CONTENT_CUSTOM_USER",
    "CONTENT_DIALOGUE_DUO_USER",
    "CONTENT_DIALOGUE_SCRIPT_USER",
    "CONTENT_SYSTEM",
    "CONTENT_USER",
    "PROMPT_COMPLEXITY_EN_RANGES",
    "PROMPT_COMPLEXITY_LABELS",
    "PROMPT_COMPLEXITY_ZH_RANGES",
    "build_storyboard_prompt",
    "build_storyboard_regenerate_prompt",
    "build_storyboard_smart_merge_repair_prompt",
    "build_storyboard_smart_merge_prompt",
    "DUO_PODCAST_STYLE_DESCRIPTIONS",
    "format_prompt_complexity_for_log",
    "format_target_language_for_log",
    "FIRST_FRAME_BATCH_COMMON_USER",
    "FIRST_FRAME_BATCH_DIALOGUE_SCRIPT_USER",
    "FIRST_FRAME_BATCH_DUO_SYSTEM",
    "FIRST_FRAME_BATCH_DUO_USER",
    "FIRST_FRAME_BATCH_SYSTEM",
    "STYLE_DESCRIPTIONS",
    "TITLE_USER",
    "get_first_frame_prompt_example",
    "get_first_frame_prompt_length_requirement",
    "get_prompt_complexity_label",
    "get_reference_description_example",
    "get_reference_description_length_requirement",
    "get_reference_description_requirement",
    "get_target_language_label",
    "get_unrestricted_language_log_label",
    "get_video_prompt_example",
    "get_video_prompt_length_requirement",
    "get_vision_description_length_requirement",
    "resolve_prompt_complexity",
    "resolve_storyboard_prompt_config",
    "resolve_target_language",
    "VIDEO_PROMPT_COMMON_STANDARD_USER",
    "VIDEO_PROMPT_DIALOGUE_SCRIPT_USER",
    "VIDEO_PROMPT_DUO_PODCAST_SINGLE_TAKE_USER",
    "VIDEO_PROMPT_SYSTEM",
]


# 新闻事实研究（生成信息）
RESEARCH_SYSTEM = """你是一名资深新闻研究员。你的任务是：基于搜索结果进行深入检索，并写出结构化、可核查的事实报告。

## 用户输入
用户可能只输入几个关键词。你需要确认其最可能指向的事件/话题。
若关键词可能对应多个不同事件，分别列出最相关的 1–3 个候选事件并清晰标注。

## 事实约束（只要事实，不要评论）
- 只陈述可核查事实：不要加入立场、评价、推测、预测或建议；避免带情绪/判断的措辞。
- 将"已确认事实"与"未经证实/早期报道/传闻"明确区分；如存在争议，分别写清各方说法。
- 尽量提供精确日期（YYYY-MM-DD）、时间（含时区，如适用）、地点、关键当事方。
- 关键事实、重大结论不要只依赖单一来源，尽量交叉验证。
- 优先使用一手/权威信息：官方通告、监管机构、法院文件、公司公告/财报、权威通讯社与主流媒体。

## 输出结构（必须使用这些标题）
1）事件确认
- 本报告聚焦的事件（1 句话）
- 关键主体（人/机构/地点）
- 为什么这些关键词指向该事件（简要说明）

2）背景与脉络
- 理解事件所需的前因、相关政策/历史、技术/行业背景（只写事实）

3）时间线（按时间顺序）
- 逐条列出：日期/时间 → 发生了什么 → 由谁确认/披露

4）影响与后果（事实性梳理）
- 直接影响：人员、服务、供应链、市场反应、执法/政策动作等（尽量量化）
- 后续影响：调查进展、诉讼/监管程序、制裁/召回/停工、组织人事变动等
- 相关方回应：官方/公司/当事方公开表态与采取的行动

5）仍待确认的信息（事实）
- 列出目前尚不清楚/仍在调查的问题，以及来源如何描述"待公布/待核实"
"""

RESEARCH_USER = """请根据以下关键词和搜索结果，生成一份结构化的事实报告。

关键词: {keywords}

搜索结果:
{search_results}
"""

# 视觉参考分析（生成参考描述）
REFERENCE_ANALYSIS_SYSTEM = """你是一个专业的视觉参考分析师，擅长从文案中识别需要稳定呈现的参考主体，并为AI图像生成提供准确、可执行的参考描述。"""

REFERENCE_ANALYSIS_USER = """请分析以下口播文案，识别出需要在视频中反复出现或重点呈现的参考主体。

口播文案：
{content}

已有参考信息（仅用于避免重复生成）：
{existing_references}

要求：
1. 只识别在文案中反复出现或对画面一致性有关键影响的参考主体（可包含人物、生物、物体、标识等）
2. 为每个参考主体生成详细的可视外观描述（用于AI图像生成）
3. 若主体在文案中以真实姓名反复出现，可保留该姓名作为参考名称；仅在文案未明确姓名时再使用职业或身份代称
4. {reference_description_requirement}
5. {reference_description_length_requirement}
6. 外观描述必须是“单张静态图可见”的瞬间状态，只写当前可见外观与姿态；禁止“从A到B、由A转为B、先A后B、后期/随后/最终”等时间变化表达
7. 【重要】不要指定任何艺术风格
8. 只输出“新增参考”，不要重复已有参考（包含同名、同主体、同描述含义都视为重复）
9. 若没有可新增项，返回空数组：{{"references": []}}

请以JSON格式输出：
{{
  "references": [
    {{
      "id": "ref_01",
      "name": "参考主体名称/代称",
      "appearance_description": "{reference_description_example}"
    }}
  ]
}}"""

# # 视频首帧设计（生成首帧图描述）
# FIRST_FRAME_SYSTEM = """你是一个专业的视频首帧设计师，擅长设计适合AI图像生成的首帧构图。"""

# FIRST_FRAME_USER = """请为以下分镜设计首帧图像的构图描述。

# 分镜内容：{voice_content}
# 视频描述：{video_prompt}
# 相关参考：{references}

# 要求：
# 1. 用英文描述首帧构图
# 2. 包含场景、人物位置、动作、表情、光线等
# 3. 描述应该能直接用于AI图像生成
# 4. 50-100词

# 请直接输出英文描述，不要输出其他内容。"""

# 视频首帧图描述批量设计_1（生成多分镜首帧图描述）
FIRST_FRAME_BATCH_SYSTEM = """你是一个专业的视频首帧设计师，擅长为连续的分镜设计视觉连贯的首帧构图。

关键原则（必须严格遵守）：
1. 你输出的是“首帧”（t=0~1s）画面，不是中段或结尾画面。
2. 每条 first_frame_prompt 必须严格对齐对应 video_prompt 的“开场可见画面”。
3. 如果 video_prompt 中包含转场/变化（如 dissolve, morph, then, after），首帧只能描述转场开始时的状态，不能跳到变化完成后的画面。
4. 避免描述连续动作链，优先给出一个可直接截图的静态构图瞬间。"""

# 视频画面设计（生成视频画面描述）
