from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import settings
from app.llm.catalog import canonicalize_llm_model, default_llm_providers
from app.providers import LLMProvider, get_llm_provider

DEFAULT_MODEL_BINDING_SEPARATOR = "::"


@dataclass
class ResolvedLLMRuntime:
    provider_id: str
    provider_name: str
    provider_type: str
    model: str
    supports_vision: bool
    provider: LLMProvider


def _normalize_models(raw_models: list[Any]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in raw_models:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _provider_pool() -> list[dict[str, Any]]:
    builtin_defaults = default_llm_providers()
    raw_pool = settings.llm_providers or builtin_defaults
    if not isinstance(raw_pool, list) or not raw_pool:
        raw_pool = builtin_defaults

    raw_pool_items = [item for item in raw_pool if isinstance(item, dict)]
    existing_ids = {
        str(item.get("id") or "").strip()
        for item in raw_pool_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    for builtin in builtin_defaults:
        builtin_id = str(builtin.get("id") or "").strip()
        if builtin_id and builtin_id not in existing_ids:
            raw_pool_items.append(dict(builtin))
            existing_ids.add(builtin_id)

    unique_raw_items: list[dict[str, Any]] = []
    seen_raw_ids: set[str] = set()
    raw_by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_pool_items:
        if not isinstance(raw, dict):
            continue
        provider_id = str(raw.get("id") or "").strip()
        if not provider_id or provider_id in seen_raw_ids:
            continue
        seen_raw_ids.add(provider_id)
        unique_raw_items.append(raw)
        raw_by_id[provider_id] = raw

    ordered_raw_items: list[dict[str, Any]] = []
    builtin_ids: set[str] = set()
    for builtin in builtin_defaults:
        builtin_id = str(builtin.get("id") or "").strip()
        if not builtin_id:
            continue
        builtin_ids.add(builtin_id)
        ordered_raw_items.append(raw_by_id.get(builtin_id, dict(builtin)))

    for raw in unique_raw_items:
        provider_id = str(raw.get("id") or "").strip()
        if not provider_id or provider_id in builtin_ids:
            continue
        ordered_raw_items.append(raw)

    default_map = {str(item.get("id") or "").strip(): item for item in builtin_defaults}

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in ordered_raw_items:
        if not isinstance(raw, dict):
            continue
        provider_id = str(raw.get("id") or "").strip()
        if not provider_id or provider_id in seen_ids:
            continue
        seen_ids.add(provider_id)

        provider_name = str(raw.get("name") or provider_id).strip() or provider_id
        base_url = str(raw.get("base_url") or "").strip()

        raw_catalog_models = raw.get("catalog_models")
        raw_enabled_models = raw.get("enabled_models")
        catalog_models = _normalize_models(
            [
                canonicalize_llm_model(
                    item,
                    provider_id=provider_id,
                    provider_name=provider_name,
                    base_url=base_url,
                )
                for item in list(raw_catalog_models or [])
            ]
        )
        enabled_models = _normalize_models(
            [
                canonicalize_llm_model(
                    item,
                    provider_id=provider_id,
                    provider_name=provider_name,
                    base_url=base_url,
                )
                for item in list(raw_enabled_models or [])
            ]
        )
        if raw_enabled_models is None and not enabled_models and catalog_models:
            enabled_models = list(catalog_models)
        if not catalog_models and enabled_models:
            catalog_models = list(enabled_models)

        default_model = canonicalize_llm_model(
            raw.get("default_model"),
            provider_id=provider_id,
            provider_name=provider_name,
            base_url=base_url,
        )
        if default_model and enabled_models and default_model not in enabled_models:
            default_model = enabled_models[0]
        if not default_model and enabled_models:
            default_model = enabled_models[0]

        provider_type = str(raw.get("provider_type") or "openai_chat").strip() or "openai_chat"
        fallback = default_map.get(provider_id)
        if fallback:
            provider_type = (
                str(fallback.get("provider_type") or provider_type).strip() or provider_type
            )

        normalized.append(
            {
                "id": provider_id,
                "name": provider_name,
                "provider_type": provider_type,
                "base_url": base_url,
                "api_key": str(raw.get("api_key") or "").strip(),
                "enabled_models": enabled_models,
                "default_model": default_model,
                "supports_vision": bool(raw.get("supports_vision")),
            }
        )

    return normalized or default_llm_providers()


def _parse_default_model_binding(raw_value: Any) -> tuple[str, str]:
    text = str(raw_value or "").strip()
    if not text:
        return "", ""
    if DEFAULT_MODEL_BINDING_SEPARATOR not in text:
        return "", text
    provider_id, model_id = text.split(DEFAULT_MODEL_BINDING_SEPARATOR, 1)
    return str(provider_id or "").strip(), str(model_id or "").strip()


def resolve_llm_runtime(
    input_data: dict[str, Any] | None = None,
    *,
    require_vision: bool = False,
    default_mode: Literal["general_first", "fast_first"] = "general_first",
) -> ResolvedLLMRuntime:
    payload = input_data or {}
    providers = _provider_pool()

    provider_by_id = {
        str(item.get("id") or "").strip(): item for item in providers if isinstance(item, dict)
    }

    requested_provider_id = str(payload.get("llm_provider") or "").strip()
    requested_model_raw = payload.get("llm_model")
    if not requested_provider_id and not str(requested_model_raw or "").strip():
        if require_vision:
            default_bindings: list[Any] = [settings.default_multimodal_llm_model]
        elif default_mode == "fast_first":
            default_bindings = [
                settings.default_fast_llm_model,
                settings.default_general_llm_model,
            ]
        else:
            default_bindings = [
                settings.default_general_llm_model,
                settings.default_fast_llm_model,
            ]
        for one_binding in default_bindings:
            default_provider_id, default_model_id = _parse_default_model_binding(one_binding)
            if default_provider_id:
                requested_provider_id = default_provider_id
            if default_model_id:
                requested_model_raw = default_model_id
            if requested_provider_id or str(requested_model_raw or "").strip():
                break

    selected = provider_by_id.get(requested_provider_id)
    if selected is None:
        configured_default = str(settings.default_llm_provider or "").strip()
        selected = provider_by_id.get(configured_default)
    if selected is None:
        selected = providers[0]

    provider_id = str(selected.get("id") or "").strip()
    provider_name = str(selected.get("name") or provider_id).strip() or provider_id
    provider_type = str(selected.get("provider_type") or "openai_chat").strip() or "openai_chat"
    base_url = str(selected.get("base_url") or "").strip()
    api_key = str(selected.get("api_key") or "").strip()
    enabled_models = _normalize_models(list(selected.get("enabled_models") or []))

    if not api_key:
        raise ValueError(f"LLM provider '{provider_name}' API key not configured")
    if not base_url:
        raise ValueError(f"LLM provider '{provider_name}' base URL not configured")

    requested_model = canonicalize_llm_model(
        requested_model_raw,
        provider_id=provider_id,
        provider_name=provider_name,
        base_url=base_url,
    )
    model = requested_model
    if enabled_models:
        if not model or model not in enabled_models:
            model = str(selected.get("default_model") or "").strip() or enabled_models[0]
    elif not model:
        model = str(selected.get("default_model") or "").strip()

    if not model:
        raise ValueError(f"LLM provider '{provider_name}' has no available model")

    supports_vision = bool(selected.get("supports_vision"))
    if require_vision and not supports_vision:
        raise ValueError(f"LLM provider '{provider_name}' does not support vision")

    provider = get_llm_provider(
        provider_type,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return ResolvedLLMRuntime(
        provider_id=provider_id,
        provider_name=provider_name,
        provider_type=provider_type,
        model=model,
        supports_vision=supports_vision,
        provider=provider,
    )
