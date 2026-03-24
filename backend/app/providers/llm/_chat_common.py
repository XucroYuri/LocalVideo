from __future__ import annotations

from typing import Any


def build_chat_messages(
    prompt: str,
    *,
    system_prompt: str | None = None,
    image_url: str | None = None,
    image_base64: str | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if image_url or image_base64:
        user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_base64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                }
            )
        elif image_url:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                }
            )
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": prompt})
    return messages


def _extract_text_fragment(
    value: Any,
    *,
    strip_strings: bool = True,
    list_joiner: str = "\n",
) -> str:
    if isinstance(value, str):
        return value.strip() if strip_strings else value
    if isinstance(value, list):
        text_parts: list[str] = []
        for item in value:
            fragment = _extract_text_fragment(
                item,
                strip_strings=strip_strings,
                list_joiner=list_joiner,
            )
            if fragment != "":
                text_parts.append(fragment)
        joined = list_joiner.join(text_parts)
        return joined.strip() if strip_strings else joined
    if isinstance(value, dict):
        for key in ("text", "content"):
            fragment = _extract_text_fragment(
                value.get(key),
                strip_strings=strip_strings,
                list_joiner=list_joiner,
            )
            if fragment != "":
                return fragment
    return ""


def extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return str(payload.get("output_text") or "").strip()

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return _extract_text_fragment(first_choice.get("text"))

    content = _extract_text_fragment(message.get("content"))
    if content:
        return content
    refusal = _extract_text_fragment(message.get("refusal"))
    if refusal:
        return refusal
    return ""


def extract_stream_delta_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return ""
    # Streaming deltas can be whitespace/newline-only; keep them as-is to avoid
    # collapsing paragraphs when chunks are concatenated downstream.
    content = _extract_text_fragment(
        delta.get("content"),
        strip_strings=False,
        list_joiner="",
    )
    if content:
        return content
    return _extract_text_fragment(
        delta.get("text"),
        strip_strings=False,
        list_joiner="",
    )
