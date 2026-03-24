"""Utilities for normalizing and extracting reference slots."""

from __future__ import annotations

from typing import Any


def normalize_reference_slots(
    raw: Any,
    *,
    allowed_reference_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    indexed_slots: list[tuple[int, int, str, str]] = []
    for idx, item in enumerate(raw):
        ref_id = ""
        ref_name = ""
        order = 10**9 + idx
        if isinstance(item, dict):
            ref_id = str(item.get("id") or item.get("reference_id") or "").strip()
            ref_name = str(item.get("name") or "").strip()
            raw_order = item.get("order")
            try:
                parsed_order = int(raw_order)
                if parsed_order > 0:
                    order = parsed_order
            except (TypeError, ValueError):
                pass
        else:
            ref_id = str(item or "").strip()

        if not ref_id:
            continue
        if allowed_reference_ids is not None and ref_id not in allowed_reference_ids:
            continue
        indexed_slots.append((order, idx, ref_id, ref_name))

    indexed_slots.sort(key=lambda item: (item[0], item[1]))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, _, ref_id, ref_name in indexed_slots:
        if ref_id in seen:
            continue
        seen.add(ref_id)
        slot: dict[str, Any] = {"order": len(normalized) + 1, "id": ref_id}
        if ref_name:
            slot["name"] = ref_name
        normalized.append(slot)
    return normalized


def extract_reference_slot_ids(
    raw: Any,
    *,
    allowed_reference_ids: set[str] | None = None,
) -> list[str]:
    slots = normalize_reference_slots(raw, allowed_reference_ids=allowed_reference_ids)
    return [
        str(slot.get("id") or "").strip() for slot in slots if str(slot.get("id") or "").strip()
    ]


def build_reference_slots_from_ids(
    reference_ids: list[str],
    original_slots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    name_by_id: dict[str, str] = {}
    for slot in original_slots or []:
        if not isinstance(slot, dict):
            continue
        slot_id = str(slot.get("id") or "").strip()
        slot_name = str(slot.get("name") or "").strip()
        if slot_id and slot_name and slot_id not in name_by_id:
            name_by_id[slot_id] = slot_name

    rebuilt: list[dict[str, Any]] = []
    for idx, ref_id in enumerate(reference_ids):
        value = str(ref_id or "").strip()
        if not value:
            continue
        slot: dict[str, Any] = {"order": idx + 1, "id": value}
        ref_name = name_by_id.get(value)
        if ref_name:
            slot["name"] = ref_name
        rebuilt.append(slot)
    return rebuilt
