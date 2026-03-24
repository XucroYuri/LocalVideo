from __future__ import annotations

import json
from typing import Any


def truncate_generation_text(text: Any, max_chars: int = 5000) -> str:
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw

    if max_chars <= 20:
        return raw[:max_chars]

    head_len = max_chars // 2
    tail_len = max_chars - head_len
    omitted = len(raw) - max_chars
    return f"{raw[:head_len]}\n... <omitted {omitted} chars> ...\n{raw[-tail_len:]}"


def format_generation_json(value: Any, max_chars: int = 5000) -> str:
    try:
        pretty = json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        pretty = str(value)
    return truncate_generation_text(pretty, max_chars=max_chars)
