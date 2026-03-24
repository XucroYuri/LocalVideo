import json
import time
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm.catalog import (
    LLM_PROVIDER_TYPE_GEMINI,
    LLM_PROVIDER_TYPE_OPENAI_CHAT,
    LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
    LLM_PROVIDER_TYPES,
    canonicalize_llm_model,
)
from app.providers import get_llm_provider
from app.providers.llm._chat_common import build_chat_messages, extract_chat_content

from ._common import (
    _mask_key,
    _normalize_anthropic_base_url,
    _normalize_gemini_base_url,
    _normalize_openai_like_base_url,
    logger,
)

router = APIRouter()


class ModelInfo(BaseModel):
    id: str
    object: str | None = None
    created: int | None = None
    owned_by: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class ModelConnectivityTestRequest(BaseModel):
    provider_type: str
    base_url: str | None = None
    api_key: str | None = None
    model: str


class ModelConnectivityTestResponse(BaseModel):
    success: bool
    model: str
    latency_ms: int | None = None
    message: str | None = None
    error: str | None = None


def _extract_text_fragment(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            fragment = _extract_text_fragment(item)
            if fragment:
                parts.append(fragment)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content"):
            fragment = _extract_text_fragment(value.get(key))
            if fragment:
                return fragment
    return ""


def _extract_openai_chat_reasoning(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""
    return _extract_text_fragment(message.get("reasoning_content"))


async def _probe_openai_chat_connectivity(
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
) -> tuple[bool, str, str]:
    payload = {
        "model": model,
        "messages": build_chat_messages(
            "Reply with exactly OK.",
            system_prompt="You are a model connectivity tester.",
        ),
        "temperature": temperature,
        # 对推理模型给出更大的上限，降低“只有 reasoning 没有最终 content”的概率。
        "max_tokens": 256,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = "Model returned empty content/reasoning"
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=45.0, trust_env=True) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = extract_chat_content(data)
        if content:
            return True, content, ""

        reasoning = _extract_openai_chat_reasoning(data)
        if reasoning:
            message = "模型联通成功（返回 reasoning_content，未返回最终 content）。"
            return True, message, ""

        choices = data.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        finish_reason = ""
        if isinstance(first_choice, dict):
            finish_reason = str(first_choice.get("finish_reason") or "")
        last_error = f"LLM returned empty content (finish_reason={finish_reason or 'unknown'})"
        logger.warning(
            "[LLM Model Test][openai_chat] attempt=%d empty response model=%s base_url=%s finish_reason=%s",
            attempt + 1,
            model,
            base_url,
            finish_reason or "unknown",
        )
    return False, "", last_error


@router.get("/models", response_model=ModelsResponse)
async def fetch_models(
    provider_type: str,
    base_url: str | None = None,
    api_key: str | None = None,
):
    normalized_type = str(provider_type or "").strip()
    if normalized_type not in LLM_PROVIDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider_type: {provider_type}",
        )

    resolved_api_key = str(api_key or "").strip()
    if not resolved_api_key:
        raise HTTPException(status_code=400, detail="API Key not configured")

    resolved_base_url = str(base_url or "").strip()
    if not resolved_base_url:
        raise HTTPException(status_code=400, detail="Base URL not configured")

    if normalized_type == LLM_PROVIDER_TYPE_GEMINI:
        normalized_base = _normalize_gemini_base_url(resolved_base_url)
        models_url = f"{normalized_base.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {resolved_api_key}",
            "Content-Type": "application/json",
        }
    elif normalized_type in {
        LLM_PROVIDER_TYPE_OPENAI_CHAT,
        LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
    }:
        normalized_base = _normalize_openai_like_base_url(resolved_base_url)
        models_url = f"{normalized_base.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {resolved_api_key}",
            "Content-Type": "application/json",
        }
    else:
        normalized_base = _normalize_anthropic_base_url(resolved_base_url)
        models_url = f"{normalized_base}/models"
        headers = {
            "x-api-key": resolved_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=True) as client:
            response = await client.get(models_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            raw_models = data.get("data") if isinstance(data, dict) else None
            if not isinstance(raw_models, list):
                raw_models = []
            models = [ModelInfo(**m) for m in raw_models if isinstance(m, dict)]
            return ModelsResponse(models=models)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Request timeout")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = str(e.response.json())
        except Exception:
            detail = e.response.text
        raise HTTPException(
            status_code=e.response.status_code,
            detail=detail or str(e),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch models: {e}")


@router.post("/models/test", response_model=ModelConnectivityTestResponse)
async def test_model_connectivity(payload: ModelConnectivityTestRequest):
    normalized_type = str(payload.provider_type or "").strip()
    if normalized_type not in LLM_PROVIDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider_type: {payload.provider_type}",
        )

    resolved_api_key = str(payload.api_key or "").strip()
    if not resolved_api_key:
        raise HTTPException(status_code=400, detail="API Key not configured")

    resolved_base_url = str(payload.base_url or "").strip()
    if not resolved_base_url:
        raise HTTPException(status_code=400, detail="Base URL not configured")
    if normalized_type == LLM_PROVIDER_TYPE_GEMINI:
        resolved_base_url = _normalize_gemini_base_url(resolved_base_url)
    elif normalized_type in {
        LLM_PROVIDER_TYPE_OPENAI_CHAT,
        LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
    }:
        resolved_base_url = _normalize_openai_like_base_url(resolved_base_url)
    else:
        resolved_base_url = _normalize_anthropic_base_url(resolved_base_url)

    resolved_model = canonicalize_llm_model(
        payload.model,
        provider_id=None,
        provider_name=None,
        base_url=resolved_base_url,
    )
    if not resolved_model:
        raise HTTPException(status_code=400, detail="Model not configured")
    resolved_model_lower = resolved_model.lower()
    test_temperature = 0.0
    if "kimi-k2.5" in resolved_model_lower:
        # Moonshot K2.5 series rejects non-default temperature values.
        test_temperature = 1.0

    test_id = uuid4().hex[:8]
    logger.info(
        "[LLM Model Test][%s] start provider_type=%s model=%s base_url=%s api_key=%s test_temperature=%.2f",
        test_id,
        normalized_type,
        resolved_model,
        resolved_base_url,
        _mask_key(resolved_api_key),
        test_temperature,
    )
    started = time.perf_counter()
    try:
        if normalized_type == LLM_PROVIDER_TYPE_OPENAI_CHAT:
            ok, content_or_message, probe_error = await _probe_openai_chat_connectivity(
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                model=resolved_model,
                temperature=test_temperature,
            )
            if not ok:
                raise RuntimeError(probe_error or "OpenAI chat connectivity probe failed")
            content = content_or_message
        else:
            llm_provider = get_llm_provider(
                normalized_type,
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                model=resolved_model,
                timeout=45.0,
            )
            response = await llm_provider.generate(
                prompt="Reply with exactly OK.",
                system_prompt="You are a model connectivity tester.",
                temperature=test_temperature,
                max_tokens=16,
            )
            content = str(response.content or "").strip()

        latency_ms = int((time.perf_counter() - started) * 1000)
        preview = content.replace("\n", " ")[:160]
        logger.info(
            "[LLM Model Test][%s] success latency_ms=%d response_preview=%s",
            test_id,
            latency_ms,
            preview,
        )
        return ModelConnectivityTestResponse(
            success=True,
            model=resolved_model,
            latency_ms=latency_ms,
            message=content or "OK",
        )
    except httpx.HTTPStatusError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = ""
        try:
            body = exc.response.json()
            response_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        except Exception:
            response_text = str(exc.response.text or "").strip()
        response_preview = response_text[:600] if response_text else ""
        logger.exception(
            "[LLM Model Test][%s] failed latency_ms=%d provider_type=%s model=%s base_url=%s status=%s error=%s response_body=%s",
            test_id,
            latency_ms,
            normalized_type,
            resolved_model,
            resolved_base_url,
            exc.response.status_code,
            str(exc) or "Unknown error",
            response_preview,
        )
        error_message = str(exc) or "Unknown error"
        is_gemini_base = "generativelanguage.googleapis.com" in resolved_base_url.lower()
        if (
            exc.response.status_code == 401
            and is_gemini_base
            and "api keys are not supported by this api" in response_text.lower()
        ):
            error_message = (
                "Gemini 鉴权失败：当前凭证不是可用于 Gemini Developer API 的 API Key。"
                "请在 Google AI Studio 创建 Gemini API Key 后重试，"
                "或改用 OAuth2 access token（例如 ya29.*）作为 API Key。"
            )
        if response_preview:
            error_message = f"{error_message}; response_body={response_preview}"
        return ModelConnectivityTestResponse(
            success=False,
            model=resolved_model,
            latency_ms=latency_ms,
            error=error_message,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "[LLM Model Test][%s] failed latency_ms=%d provider_type=%s model=%s base_url=%s error=%s",
            test_id,
            latency_ms,
            normalized_type,
            resolved_model,
            resolved_base_url,
            str(exc) or "Unknown error",
        )
        return ModelConnectivityTestResponse(
            success=False,
            model=resolved_model,
            latency_ms=latency_ms,
            error=str(exc) or "Unknown error",
        )
