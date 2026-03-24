from __future__ import annotations

import re

from app.providers.wan2gp import normalize_status_message, should_advance_status

_PERCENT_PATTERN = re.compile(r"(\d{1,3})%")


def extract_runtime_percent(message: str | None) -> int | None:
    if not message:
        return None
    match = _PERCENT_PATTERN.search(message)
    if not match:
        return None
    try:
        return max(0, min(99, int(match.group(1))))
    except Exception:
        return None


def resolve_runtime_status(current: str | None, incoming: str | None) -> str | None:
    normalized = normalize_status_message(incoming)
    if not normalized:
        return None
    if current and not should_advance_status(current, normalized):
        return None
    return normalized
