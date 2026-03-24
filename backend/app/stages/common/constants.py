from __future__ import annotations

import re

EMOJI_PATTERN = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # flags
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001faff"
    "\U00002700-\U000027bf"
    "\U00002600-\U000026ff"
    "\u200d"  # zero width joiner
    "\u20e3"  # keycap
    "\ufe0f"  # variation selector-16
    "]",
    flags=re.UNICODE,
)
