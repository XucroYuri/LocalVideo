import json
import re
from typing import Any

SCRIPT_MODE_SINGLE = "single"
SCRIPT_MODE_CUSTOM = "custom"
SCRIPT_MODE_DUO_PODCAST = "duo_podcast"
SCRIPT_MODE_DIALOGUE_SCRIPT = "dialogue_script"
SUPPORTED_SCRIPT_MODES = {
    SCRIPT_MODE_CUSTOM,
    SCRIPT_MODE_SINGLE,
    SCRIPT_MODE_DUO_PODCAST,
    SCRIPT_MODE_DIALOGUE_SCRIPT,
}
MIN_DIALOGUE_MAX_ROLES = 1
MAX_DIALOGUE_MAX_ROLES = 20
DEFAULT_DIALOGUE_MAX_ROLES = MAX_DIALOGUE_MAX_ROLES

NARRATOR_SPEAKER_ID = "narrator"
NARRATOR_ALIASES = {
    "narrator",
    "旁白",
    "画外音",
    "vo",
    "voiceover",
    "voice_over",
}
DEFAULT_NARRATOR_NAME = "画外音"
REF_ID_PATTERN = re.compile(r"^ref_(\d+)$")
DEFAULT_SINGLE_ROLE_ID = "ref_01"
DEFAULT_SINGLE_ROLE_NAME = "讲述者"
DUO_ROLE_1_ID = "ref_01"
DUO_ROLE_2_ID = "ref_02"
DUO_SCENE_ROLE_ID = "ref_03"
DUO_SCENE_ROLE_NAME = "播客场景"
DUO_ROLE_1_DEFAULT_NAME = "讲述者1"
DUO_ROLE_2_DEFAULT_NAME = "讲述者2"
DUO_ROLE_1_DEFAULT_DESCRIPTION = (
    "冷静理性，擅长先给结论再拆解逻辑与证据；表达克制清晰，像在带着听众做结构化梳理。"
)
DUO_ROLE_2_DEFAULT_DESCRIPTION = (
    "好奇敏锐，擅长追问关键细节并把抽象概念翻译成生活化表达；语气亲切有节奏，负责推进讨论。"
)
DUO_SCENE_DEFAULT_DESCRIPTION = "双人播客录音间，桌面麦克风对谈，氛围专业但轻松。"
DUO_SEAT_LEFT = "left"
DUO_SEAT_RIGHT = "right"


def normalize_dialogue_max_roles(
    value: Any,
    *,
    default: int = DEFAULT_DIALOGUE_MAX_ROLES,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_DIALOGUE_MAX_ROLES, min(MAX_DIALOGUE_MAX_ROLES, parsed))


def resolve_script_mode(value: Any, default: str = SCRIPT_MODE_SINGLE) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_SCRIPT_MODES:
        return normalized
    return default


def is_multi_script_mode(mode: str) -> bool:
    resolved = resolve_script_mode(mode)
    return resolved in {SCRIPT_MODE_CUSTOM, SCRIPT_MODE_DUO_PODCAST, SCRIPT_MODE_DIALOGUE_SCRIPT}


def _normalize_role_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-zA-Z0-9_\-]", "", text)
    return text.lower()


def _normalize_role_name(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_role_description(value: Any) -> str:
    return str(value or "").strip()


def is_reference_id(value: Any) -> bool:
    return REF_ID_PATTERN.fullmatch(str(value or "").strip()) is not None


def generate_next_reference_id(existing_ids: list[str] | set[str]) -> str:
    used_numbers: set[int] = set()
    for item in existing_ids:
        match = REF_ID_PATTERN.fullmatch(str(item or "").strip())
        if not match:
            continue
        used_numbers.add(int(match.group(1)))
    next_num = 1
    while next_num in used_numbers:
        next_num += 1
    return f"ref_{next_num:02d}"


def _normalize_duo_seat_side(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {DUO_SEAT_LEFT, "左"}:
        return DUO_SEAT_LEFT
    if normalized in {DUO_SEAT_RIGHT, "右"}:
        return DUO_SEAT_RIGHT
    return None


def _opposite_duo_seat_side(value: str) -> str:
    return DUO_SEAT_RIGHT if value == DUO_SEAT_LEFT else DUO_SEAT_LEFT


def _resolve_duo_seat_pair(
    role_1_seat: str | None,
    role_2_seat: str | None,
) -> tuple[str, str]:
    if role_1_seat and role_2_seat:
        if role_1_seat == role_2_seat:
            role_2_seat = _opposite_duo_seat_side(role_1_seat)
        return (role_1_seat, role_2_seat)
    if role_1_seat and not role_2_seat:
        return (role_1_seat, _opposite_duo_seat_side(role_1_seat))
    if role_2_seat and not role_1_seat:
        return (_opposite_duo_seat_side(role_2_seat), role_2_seat)
    return (DUO_SEAT_LEFT, DUO_SEAT_RIGHT)


def normalize_roles(
    raw_roles: Any,
    *,
    script_mode: str,
    max_roles: int,
) -> list[dict[str, Any]]:
    mode = resolve_script_mode(script_mode)

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if isinstance(raw_roles, list):
        for index, item in enumerate(raw_roles):
            if not isinstance(item, dict):
                continue

            role_id = _normalize_role_id(item.get("id"))
            if not role_id:
                role_id = f"ref_{index + 1:02d}"
            raw_role_name = (
                item.get("name")
                or item.get("speaker_name")
                or item.get("speaker")
                or item.get("role")
            )
            if mode in {SCRIPT_MODE_SINGLE, SCRIPT_MODE_DUO_PODCAST} and _is_narrator_label(
                raw_role_name
            ):
                continue
            if role_id in seen_ids:
                continue
            seen_ids.add(role_id)

            default_role_name = (
                DEFAULT_NARRATOR_NAME if _is_narrator_label(raw_role_name) else f"角色{index + 1}"
            )
            normalized.append(
                {
                    "id": role_id if is_reference_id(role_id) else f"ref_{len(normalized) + 1:02d}",
                    "name": _normalize_role_name(
                        DEFAULT_NARRATOR_NAME
                        if _is_narrator_label(raw_role_name)
                        else item.get("name"),
                        default_role_name,
                    ),
                    "description": _normalize_role_description(item.get("description")),
                    "seat_side": _normalize_duo_seat_side(item.get("seat_side")),
                    "locked": bool(item.get("locked", False)),
                }
            )

    if mode == SCRIPT_MODE_SINGLE:
        role_1 = next(
            (role for role in normalized if str(role.get("id") or "") == DEFAULT_SINGLE_ROLE_ID),
            None,
        ) or (normalized[0] if normalized else {})
        return [
            {
                "id": DEFAULT_SINGLE_ROLE_ID,
                "name": _normalize_role_name(role_1.get("name"), DEFAULT_SINGLE_ROLE_NAME),
                "description": _normalize_role_description(role_1.get("description")),
                "seat_side": None,
                "locked": True,
            }
        ]

    if mode == SCRIPT_MODE_DUO_PODCAST:
        role_1 = next(
            (role for role in normalized if str(role.get("id") or "") == DUO_ROLE_1_ID), None
        ) or (normalized[0] if len(normalized) > 0 else {})
        role_2 = next(
            (role for role in normalized if str(role.get("id") or "") == DUO_ROLE_2_ID), None
        ) or (normalized[1] if len(normalized) > 1 else {})
        scene_role = next(
            (role for role in normalized if str(role.get("id") or "") == DUO_SCENE_ROLE_ID),
            None,
        ) or (normalized[2] if len(normalized) > 2 else {})
        role_1_seat, role_2_seat = _resolve_duo_seat_pair(
            _normalize_duo_seat_side(role_1.get("seat_side")),
            _normalize_duo_seat_side(role_2.get("seat_side")),
        )
        return [
            {
                "id": DUO_ROLE_1_ID,
                "name": _normalize_role_name(role_1.get("name"), DUO_ROLE_1_DEFAULT_NAME),
                "description": _normalize_role_name(
                    _normalize_role_description(role_1.get("description")),
                    DUO_ROLE_1_DEFAULT_DESCRIPTION,
                ),
                "seat_side": role_1_seat,
                "locked": True,
            },
            {
                "id": DUO_ROLE_2_ID,
                "name": _normalize_role_name(role_2.get("name"), DUO_ROLE_2_DEFAULT_NAME),
                "description": _normalize_role_name(
                    _normalize_role_description(role_2.get("description")),
                    DUO_ROLE_2_DEFAULT_DESCRIPTION,
                ),
                "seat_side": role_2_seat,
                "locked": True,
            },
            {
                "id": DUO_SCENE_ROLE_ID,
                "name": _normalize_role_name(scene_role.get("name"), DUO_SCENE_ROLE_NAME),
                "description": _normalize_role_name(
                    _normalize_role_description(scene_role.get("description")),
                    DUO_SCENE_DEFAULT_DESCRIPTION,
                ),
                "seat_side": None,
                "locked": True,
            },
        ]

    if max_roles <= 0:
        max_roles = 1
    clipped = normalized[:max_roles]
    for idx, role in enumerate(clipped):
        if not str(role.get("id") or "").strip() or not is_reference_id(role.get("id")):
            existing_ids = {
                str(item.get("id") or "").strip()
                for item in clipped
                if str(item.get("id") or "").strip()
            }
            role["id"] = generate_next_reference_id(existing_ids)
        role["locked"] = False
        if not str(role.get("name") or "").strip():
            role["name"] = f"角色{idx + 1}"
        role["seat_side"] = None
    return clipped


def _is_narrator_label(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in NARRATOR_ALIASES


def _build_role_name_lookup(roles: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for role in roles:
        role_id = str(role.get("id") or "").strip()
        role_name = str(role.get("name") or "").strip()
        if role_id:
            mapping[role_id.lower()] = role_id
        if role_name:
            mapping[role_name.lower()] = role_id
    return mapping


def _resolve_duo_speaker_roles(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for role_id in (DUO_ROLE_1_ID, DUO_ROLE_2_ID):
        matched = next(
            (role for role in roles if str(role.get("id") or "").strip() == role_id),
            None,
        )
        if matched is None:
            continue
        resolved.append(matched)
        seen_ids.add(role_id)

    if len(resolved) >= 2:
        return resolved

    for role in roles:
        role_id = str(role.get("id") or "").strip()
        if not role_id or role_id == DUO_SCENE_ROLE_ID or role_id in seen_ids:
            continue
        resolved.append(role)
        seen_ids.add(role_id)
        if len(resolved) >= 2:
            break

    return resolved


def _upsert_dialogue_role(
    roles: list[dict[str, Any]],
    *,
    name: str,
    max_roles: int,
) -> str:
    role_count = len(roles)
    if role_count >= max_roles:
        raise ValueError(f"角色数量超过上限（最多 {max_roles} 人）")
    existing_ids = {
        str(role.get("id") or "").strip() for role in roles if str(role.get("id") or "").strip()
    }
    new_id = generate_next_reference_id(existing_ids)
    roles.append(
        {
            "id": new_id,
            "name": name or f"角色{role_count + 1}",
            "description": "",
            "seat_side": None,
            "locked": False,
        }
    )
    return new_id


def _ensure_narrator_role(roles: list[dict[str, Any]]) -> dict[str, Any]:
    existing = next(
        (
            role
            for role in roles
            if _is_narrator_label(role.get("name"))
            or str(role.get("id") or "").strip() == NARRATOR_SPEAKER_ID
        ),
        None,
    )
    if existing is not None:
        if not is_reference_id(existing.get("id")):
            existing_ids = [
                str(role.get("id") or "").strip()
                for role in roles
                if str(role.get("id") or "").strip() and role is not existing
            ]
            existing["id"] = generate_next_reference_id(existing_ids)
        existing["name"] = str(existing.get("name") or "").strip() or DEFAULT_NARRATOR_NAME
        existing["locked"] = False
        existing["seat_side"] = None
        return existing

    narrator_role = {
        "id": generate_next_reference_id(
            [
                str(role.get("id") or "").strip()
                for role in roles
                if str(role.get("id") or "").strip()
            ]
        ),
        "name": DEFAULT_NARRATOR_NAME,
        "description": "",
        "seat_side": None,
        "locked": False,
    }
    roles.append(narrator_role)
    return narrator_role


def _parse_line_item(item: Any) -> tuple[str, str]:
    if not isinstance(item, dict):
        return ("", "")

    if "speaker_id" in item or "speaker_name" in item or "text" in item:
        speaker = str(item.get("speaker_id") or item.get("speaker_name") or "").strip()
        text = str(item.get("text") or "").strip()
        return (speaker, text)

    if len(item) == 1:
        only_key = next(iter(item.keys()))
        speaker = str(only_key or "").strip()
        text = str(item.get(only_key) or "").strip()
        return (speaker, text)

    speaker = str(item.get("role") or item.get("speaker") or "").strip()
    text = str(item.get("content") or "").strip()
    return (speaker, text)


def normalize_dialogue_lines(
    raw_lines: Any,
    *,
    roles: list[dict[str, Any]],
    script_mode: str,
    max_roles: int,
    allow_role_autofill: bool = True,
    fallback_text: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mode = resolve_script_mode(script_mode)
    normalized_roles = normalize_roles(roles, script_mode=mode, max_roles=max_roles)
    fallback_line_text = str(fallback_text or "").strip()

    if mode == SCRIPT_MODE_SINGLE:
        single_role = (
            normalized_roles[0]
            if normalized_roles
            else {
                "id": DEFAULT_SINGLE_ROLE_ID,
                "name": DEFAULT_SINGLE_ROLE_NAME,
            }
        )
        single_role_id = str(single_role.get("id") or DEFAULT_SINGLE_ROLE_ID)
        single_role_name = str(single_role.get("name") or DEFAULT_SINGLE_ROLE_NAME).strip()

        merged_texts: list[str] = []
        items = raw_lines if isinstance(raw_lines, list) else []
        for item in items:
            _, text = _parse_line_item(item)
            text = text.strip()
            if text:
                merged_texts.append(text)
        if not merged_texts and fallback_line_text:
            merged_texts.append(fallback_line_text)
        merged_text = "".join(merged_texts).strip()
        if not merged_text:
            return (normalized_roles, [])
        return (
            normalized_roles,
            [
                {
                    "id": "line_001",
                    "speaker_id": single_role_id,
                    "speaker_name": single_role_name,
                    "text": merged_text,
                    "order": 0,
                }
            ],
        )

    lines: list[dict[str, Any]] = []
    items = raw_lines if isinstance(raw_lines, list) else []
    duo_speaker_roles = (
        _resolve_duo_speaker_roles(normalized_roles) if mode == SCRIPT_MODE_DUO_PODCAST else []
    )
    role_name_lookup = (
        _build_role_name_lookup(duo_speaker_roles)
        if mode == SCRIPT_MODE_DUO_PODCAST
        else _build_role_name_lookup(normalized_roles)
    )
    duo_unmapped_names: list[str] = []

    for index, item in enumerate(items):
        speaker_raw, text = _parse_line_item(item)
        if not text:
            continue

        speaker_id = ""
        speaker_name = ""
        speaker_lookup_key = speaker_raw.lower()

        if mode in {SCRIPT_MODE_DIALOGUE_SCRIPT, SCRIPT_MODE_CUSTOM} and _is_narrator_label(
            speaker_raw
        ):
            narrator_role = _ensure_narrator_role(normalized_roles)
            role_name_lookup = _build_role_name_lookup(normalized_roles)
            speaker_id = str(narrator_role.get("id") or DEFAULT_SINGLE_ROLE_ID)
            speaker_name = (
                str(narrator_role.get("name") or DEFAULT_NARRATOR_NAME).strip()
                or DEFAULT_NARRATOR_NAME
            )
        elif speaker_lookup_key in role_name_lookup:
            speaker_id = role_name_lookup[speaker_lookup_key]
        elif mode == SCRIPT_MODE_DUO_PODCAST:
            if not allow_role_autofill:
                raise ValueError(f"角色不存在: {speaker_raw}")
            if speaker_raw:
                if speaker_raw in duo_unmapped_names:
                    mapped_index = duo_unmapped_names.index(speaker_raw)
                    mapped_role = duo_speaker_roles[mapped_index]
                    mapped_role["name"] = speaker_raw
                    speaker_id = str(mapped_role.get("id") or "")
                elif len(duo_unmapped_names) < len(duo_speaker_roles):
                    duo_unmapped_names.append(speaker_raw)
                    mapped_index = duo_unmapped_names.index(speaker_raw)
                    mapped_role = duo_speaker_roles[mapped_index]
                    mapped_role["name"] = speaker_raw
                    speaker_id = str(mapped_role.get("id") or "")
                else:
                    raise ValueError("角色数量超过上限（双人播客固定 2 个对话角色）")
            if not speaker_id:
                default_role = duo_speaker_roles[0] if duo_speaker_roles else {}
                speaker_id = str(default_role.get("id") or DUO_ROLE_1_ID)
        else:
            if speaker_raw and allow_role_autofill:
                speaker_id = _upsert_dialogue_role(
                    normalized_roles,
                    name=speaker_raw,
                    max_roles=max_roles,
                )
                role_name_lookup = _build_role_name_lookup(normalized_roles)
            elif speaker_raw:
                raise ValueError(f"角色不存在: {speaker_raw}")
            else:
                narrator_role = _ensure_narrator_role(normalized_roles)
                role_name_lookup = _build_role_name_lookup(normalized_roles)
                speaker_id = str(narrator_role.get("id") or DEFAULT_SINGLE_ROLE_ID)
                speaker_name = str(narrator_role.get("name") or DEFAULT_NARRATOR_NAME).strip()

        if not speaker_id:
            narrator_role = _ensure_narrator_role(normalized_roles)
            role_name_lookup = _build_role_name_lookup(normalized_roles)
            speaker_id = str(narrator_role.get("id") or DEFAULT_SINGLE_ROLE_ID)
            speaker_name = str(narrator_role.get("name") or DEFAULT_NARRATOR_NAME).strip()

        if not speaker_name:
            role = next(
                (r for r in normalized_roles if str(r.get("id") or "") == speaker_id),
                None,
            )
            speaker_name = str((role or {}).get("name") or speaker_raw or speaker_id).strip()

        line_id = ""
        if isinstance(item, dict):
            line_id = str(item.get("id") or "").strip()
        if not line_id:
            line_id = f"line_{index + 1:03d}"

        lines.append(
            {
                "id": line_id,
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
                "text": text,
                "order": len(lines),
            }
        )

    if not lines and fallback_line_text:
        if mode == SCRIPT_MODE_DUO_PODCAST:
            default_role = duo_speaker_roles[0] if duo_speaker_roles else {}
            default_speaker_id = str(default_role.get("id") or DUO_ROLE_1_ID)
            default_speaker_name = str(default_role.get("name") or DUO_ROLE_1_DEFAULT_NAME).strip()
        else:
            default_role = normalized_roles[0] if normalized_roles else {}
            default_speaker_id = str(default_role.get("id") or DEFAULT_SINGLE_ROLE_ID)
            default_speaker_name = str(default_role.get("name") or DEFAULT_SINGLE_ROLE_NAME).strip()
        lines.append(
            {
                "id": "line_001",
                "speaker_id": default_speaker_id,
                "speaker_name": default_speaker_name,
                "text": fallback_line_text,
                "order": 0,
            }
        )

    lines = merge_consecutive_dialogue_lines(lines)
    return (normalized_roles, lines)


def merge_consecutive_dialogue_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent lines that belong to the same speaker."""
    merged: list[dict[str, Any]] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        speaker_id = str(item.get("speaker_id") or "").strip() or DEFAULT_SINGLE_ROLE_ID
        speaker_name = str(item.get("speaker_name") or "").strip()
        if _is_narrator_label(speaker_name):
            speaker_name = speaker_name or DEFAULT_NARRATOR_NAME

        line_id = str(item.get("id") or "").strip() or f"line_{len(merged) + 1:03d}"
        if merged and str(merged[-1].get("speaker_id") or "").strip() == speaker_id:
            previous_text = str(merged[-1].get("text") or "").strip()
            merged[-1]["text"] = f"{previous_text}{text}" if previous_text else text
            continue

        merged.append(
            {
                **item,
                "id": line_id,
                "speaker_id": speaker_id,
                "speaker_name": speaker_name or speaker_id,
                "text": text,
                "order": len(merged),
            }
        )

    for index, item in enumerate(merged):
        item["order"] = index

    return merged


def flatten_dialogue_text(lines: list[dict[str, Any]]) -> str:
    if not lines:
        return ""
    texts = [str(item.get("text") or "").strip() for item in lines]
    return "".join(text for text in texts if text)


def build_dialogue_import_lines(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("dialogue_lines", "dialogue", "lines", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def parse_dialogue_json_payload(raw_text: str) -> list[Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"导入内容不是有效 JSON: {exc}") from exc
    lines = build_dialogue_import_lines(payload)
    if not lines:
        raise ValueError("导入内容为空或格式错误，请使用数组格式")
    return lines
