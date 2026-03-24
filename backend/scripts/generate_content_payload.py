#!/usr/bin/env python3
"""Generate mode-specific dialogue import payloads for `/stages/content/dialogue/import`.

Supported script modes:
- single
- duo_podcast
- dialogue_script

The generated JSON can be uploaded directly from the Content panel.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

SCRIPT_MODE_SINGLE = "single"
SCRIPT_MODE_DUO = "duo_podcast"
SCRIPT_MODE_DIALOGUE = "dialogue_script"


@dataclass(frozen=True)
class RoleTemplate:
    role_id: str
    name: str
    description: str
    seat_side: str | None = None
    locked: bool = False


def _normalize_topic(topic: str) -> str:
    value = str(topic or "").strip()
    return value or "城市门店服务争议事件"


def _normalize_title(title: str | None, topic: str, mode: str) -> str:
    if title and str(title).strip():
        return str(title).strip()
    suffix = {
        SCRIPT_MODE_SINGLE: "单人口播",
        SCRIPT_MODE_DUO: "双人播客",
        SCRIPT_MODE_DIALOGUE: "台词剧本",
    }[mode]
    return f"{topic}_{suffix}"


def _coerce_line_count(value: int, *, mode: str) -> int:
    minimum = 1 if mode == SCRIPT_MODE_SINGLE else 4
    maximum = 40
    return max(minimum, min(maximum, int(value)))


def _coerce_role_count(value: int) -> int:
    return max(1, min(8, int(value)))


def build_single_payload(topic: str, title: str, line_count: int) -> dict:
    segments = [
        f"今天我们聊聊{topic}。",
        "先给结论：争议的核心不是声音大，而是信息是否透明。",
        "站在消费者视角，大家真正关心的是标准、价格和体验是否一致。",
        "站在商家视角，运营成本、出品效率和规模化也有现实压力。",
        "当双方都只强调自己的合理性，沟通就容易走向对立。",
        "所以真正的解法，是把关键事实公开，把规则说清楚，把反馈闭环做好。",
        "最后落到一句话：长期信任，永远比短期解释更有价值。",
    ]
    merged = "".join(segments[:line_count]).strip()
    return {
        "title": title,
        "roles": [
            {
                "name": "讲述者",
                "description": "冷静清晰，擅长结构化说明重点。",
            }
        ],
        "dialogue_lines": [
            {
                "name": "讲述者",
                "text": merged,
            }
        ],
    }


def _duo_roles() -> list[RoleTemplate]:
    return [
        RoleTemplate(
            role_id="role_1",
            name="讲述者1",
            description="先给结论，再拆解逻辑。",
            seat_side="left",
            locked=True,
        ),
        RoleTemplate(
            role_id="role_2",
            name="讲述者2",
            description="追问细节，把抽象问题讲清楚。",
            seat_side="right",
            locked=True,
        ),
        RoleTemplate(
            role_id="scene",
            name="播客场景",
            description="双人播客录音间，桌面麦克风对谈，环境整洁。",
            seat_side=None,
            locked=True,
        ),
    ]


def build_duo_payload(topic: str, title: str, line_count: int) -> dict:
    line_pool = [
        ("讲述者1", f"先抛问题：{topic}为什么会突然引爆讨论？"),
        ("讲述者2", "因为表面看是单点冲突，底层其实是预期管理失衡。"),
        ("讲述者1", "对，用户期待的是稳定体验，而不是临时解释。"),
        ("讲述者2", "那企业该怎么做？先把规则写明，再把执行做实。"),
        ("讲述者1", "另外要把反馈机制前置，别等舆论发酵后才补救。"),
        ("讲述者2", "总结一下：透明、可验证、可追责，这三件事缺一不可。"),
        ("讲述者1", "如果这三件事做到位，争议会小很多，信任也会更稳。"),
        ("讲述者2", "这就是今天的重点，欢迎你把看法写在评论区。"),
    ]
    selected = line_pool[:line_count]
    dialogue_lines: list[dict] = []
    for speaker_name, text in selected:
        dialogue_lines.append(
            {
                "speaker_name": speaker_name,
                "text": text,
            }
        )

    roles_payload: list[dict] = []
    for role in _duo_roles()[:2]:
        roles_payload.append(
            {
                "name": role.name,
                "description": role.description,
            }
        )

    return {
        "title": title,
        "roles": roles_payload,
        "dialogue_lines": dialogue_lines,
    }


def _dialogue_role_pool(topic: str) -> list[RoleTemplate]:
    return [
        RoleTemplate("role_1", "主持人", f"掌控节奏，围绕{topic}持续追问。"),
        RoleTemplate("role_2", "当事人", "提供一线信息，解释决策过程。"),
        RoleTemplate("role_3", "行业观察员", "补充背景，评估影响与趋势。"),
        RoleTemplate("role_4", "用户代表", "强调真实体验与诉求。"),
        RoleTemplate("role_5", "法务顾问", "提示边界与合规要点。"),
        RoleTemplate("role_6", "运营负责人", "给出执行方案与落地路径。"),
        RoleTemplate("role_7", "数据分析师", "用关键指标支撑判断。"),
        RoleTemplate("role_8", "评论员", "总结观点并提出行动建议。"),
    ]


def build_dialogue_payload(topic: str, title: str, line_count: int, role_count: int) -> dict:
    roles = _dialogue_role_pool(topic)[:role_count]
    if not roles:
        roles = _dialogue_role_pool(topic)[:1]

    base_lines = [
        "我们先对齐事实，再讨论立场。",
        "当前争议最大的点，是信息披露和执行口径不一致。",
        "从用户反馈看，最在意的是规则透明和补偿边界。",
        "从行业经验看，越早公开标准，越能减少误读。",
        "如果要快速修复，建议先做分层沟通和进度公示。",
        "中长期需要把流程固化，避免再次出现同类问题。",
        "我们把可执行动作拆成三步：澄清、纠偏、复盘。",
        "最后给观众一个可验证的时间表和责任人。",
    ]

    dialogue_lines: list[dict] = []
    for idx in range(line_count):
        role = roles[idx % len(roles)]
        text = base_lines[idx % len(base_lines)]
        if idx == 0:
            text = f"围绕{topic}，今天这场讨论先从核心矛盾开始。"
        dialogue_lines.append(
            {
                "speaker_name": role.name,
                "text": text,
            }
        )

    roles_payload = [
        {
            "name": role.name,
            "description": role.description,
        }
        for role in roles
    ]
    return {
        "title": title,
        "roles": roles_payload,
        "dialogue_lines": dialogue_lines,
    }


def build_payload(
    *,
    mode: str,
    topic: str,
    title: str | None,
    line_count: int,
    role_count: int,
) -> dict:
    normalized_topic = _normalize_topic(topic)
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in {SCRIPT_MODE_SINGLE, SCRIPT_MODE_DUO, SCRIPT_MODE_DIALOGUE}:
        raise ValueError(f"Unsupported mode: {mode}")

    normalized_title = _normalize_title(title, normalized_topic, normalized_mode)
    normalized_line_count = _coerce_line_count(line_count, mode=normalized_mode)

    if normalized_mode == SCRIPT_MODE_SINGLE:
        return build_single_payload(normalized_topic, normalized_title, normalized_line_count)
    if normalized_mode == SCRIPT_MODE_DUO:
        return build_duo_payload(normalized_topic, normalized_title, normalized_line_count)
    return build_dialogue_payload(
        normalized_topic,
        normalized_title,
        normalized_line_count,
        _coerce_role_count(role_count),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate minimal JSON payload for content dialogue import upload."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=[SCRIPT_MODE_SINGLE, SCRIPT_MODE_DUO, SCRIPT_MODE_DIALOGUE],
        help="Script mode.",
    )
    parser.add_argument(
        "--topic",
        default="城市门店服务争议事件",
        help="Topic to weave into generated copy.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional explicit title. If omitted, auto-generated from topic and mode.",
    )
    parser.add_argument(
        "--line-count",
        type=int,
        default=8,
        help="Dialogue line count (single mode will merge into one paragraph).",
    )
    parser.add_argument(
        "--role-count",
        type=int,
        default=3,
        help="Role count for dialogue_script mode.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional output file path; prints to stdout when omitted.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(
        mode=args.mode,
        topic=args.topic,
        title=args.title,
        line_count=args.line_count,
        role_count=args.role_count,
    )
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if args.compact
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )

    output_path = Path(str(args.output or "").strip()) if args.output else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
        print(f"[generate_content_payload] wrote: {output_path}")
        return

    print(text)


if __name__ == "__main__":
    main()
