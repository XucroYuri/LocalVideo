from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

DEFAULT_KLING_BASE_URL = "https://api-beijing.klingai.com"
DEFAULT_KLING_TOKEN_TTL_SECONDS = 1800
DEFAULT_KLING_TOKEN_NBF_SKEW_SECONDS = 5


def _normalize_secret_like_value(value: str | None) -> str:
    return str(value or "").strip().strip("\"'").strip()


def normalize_kling_access_key(access_key: str | None) -> str:
    return _normalize_secret_like_value(access_key)


def normalize_kling_secret_key(secret_key: str | None) -> str:
    return _normalize_secret_like_value(secret_key)


def normalize_kling_base_url(base_url: str | None) -> str:
    normalized = str(base_url or DEFAULT_KLING_BASE_URL).strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_KLING_BASE_URL
    return f"{parsed.scheme}://{parsed.netloc}"


def is_kling_configured(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
) -> bool:
    resolved_access_key = normalize_kling_access_key(access_key)
    resolved_secret_key = normalize_kling_secret_key(secret_key)
    return bool(resolved_access_key and resolved_secret_key)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def build_kling_api_token(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
    now: int | float | None = None,
    ttl_seconds: int = DEFAULT_KLING_TOKEN_TTL_SECONDS,
    nbf_skew_seconds: int = DEFAULT_KLING_TOKEN_NBF_SKEW_SECONDS,
) -> str:
    resolved_access_key = normalize_kling_access_key(access_key)
    resolved_secret_key = normalize_kling_secret_key(secret_key)
    if not resolved_access_key or not resolved_secret_key:
        raise ValueError("可灵 Access Key / Secret Key 未配置")

    now_ts = int(now if now is not None else time.time())
    payload = {
        "iss": resolved_access_key,
        "exp": now_ts + max(int(ttl_seconds or DEFAULT_KLING_TOKEN_TTL_SECONDS), 1),
        "nbf": now_ts - max(int(nbf_skew_seconds or DEFAULT_KLING_TOKEN_NBF_SKEW_SECONDS), 0),
    }
    header = {
        "alg": "HS256",
        "typ": "JWT",
    }

    encoded_header = _base64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(
        resolved_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def build_kling_auth_headers(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
) -> dict[str, str]:
    token = build_kling_api_token(
        access_key=access_key,
        secret_key=secret_key,
    )
    return {"Authorization": f"Bearer {token}"}
