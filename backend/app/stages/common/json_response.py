from __future__ import annotations

import json
import re


def parse_json_response(content: str) -> dict:
    content = content.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if json_match:
        content = json_match.group(1).strip()

    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx != -1 and end_idx != -1:
        content = content[start_idx : end_idx + 1]

    return json.loads(content)
