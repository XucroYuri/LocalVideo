"""Helpers for extracting stable structured fields from partial JSON text streams."""

from __future__ import annotations

import json
from typing import Any


def extract_json_string_value(text: str, key: str) -> str | None:
    """Extract a complete JSON string value by key from partial JSON text.

    Returns None when key/string is not found or string is still incomplete.
    """
    key_pos = text.find(f'"{key}"')
    if key_pos < 0:
        return None
    colon_pos = text.find(":", key_pos)
    if colon_pos < 0:
        return None

    i = colon_pos + 1
    length = len(text)
    while i < length and text[i].isspace():
        i += 1
    if i >= length or text[i] != '"':
        return None

    i += 1
    escaped = False
    value_chars: list[str] = []
    while i < length:
        ch = text[i]
        if escaped:
            value_chars.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\":
            value_chars.append(ch)
            escaped = True
            i += 1
            continue
        if ch == '"':
            try:
                return json.loads(f'"{"".join(value_chars)}"')
            except Exception:
                return None
        value_chars.append(ch)
        i += 1
    return None


def extract_json_array_items(text: str, key: str) -> list[Any]:
    """Extract all currently complete array items by key from partial JSON text."""
    array_start = _find_array_start(text, key)
    if array_start < 0:
        return []

    i = array_start + 1
    length = len(text)
    in_string = False
    escaped = False
    nested_depth = 0
    token_chars: list[str] = []
    items: list[Any] = []

    def flush_token() -> None:
        token = "".join(token_chars).strip()
        token_chars.clear()
        if not token:
            return
        try:
            items.append(json.loads(token))
        except Exception:
            return

    while i < length:
        ch = text[i]
        if in_string:
            token_chars.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            token_chars.append(ch)
            i += 1
            continue

        if ch in "{[":
            nested_depth += 1
            token_chars.append(ch)
            i += 1
            continue

        if ch == "," and nested_depth == 0:
            flush_token()
            i += 1
            continue

        if ch == "]":
            if nested_depth == 0:
                flush_token()
                return items
            nested_depth -= 1
            token_chars.append(ch)
            i += 1
            continue

        if ch == "}" and nested_depth > 0:
            nested_depth -= 1
            token_chars.append(ch)
            i += 1
            continue

        token_chars.append(ch)
        i += 1

    # Stream not ended yet; include only token that is already valid JSON.
    flush_token()
    return items


def _find_array_start(text: str, key: str) -> int:
    key_pos = text.find(f'"{key}"')
    if key_pos < 0:
        return -1
    colon_pos = text.find(":", key_pos)
    if colon_pos < 0:
        return -1
    i = colon_pos + 1
    while i < len(text) and text[i].isspace():
        i += 1
    if i < len(text) and text[i] == "[":
        return i
    return -1
