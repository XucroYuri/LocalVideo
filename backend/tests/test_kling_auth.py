import base64
import json

import pytest

from app.providers.kling_auth import build_kling_api_token


def _decode_base64url(value: str) -> dict[str, object]:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8"))


def test_build_kling_api_token_from_access_key_and_secret_key() -> None:
    token = build_kling_api_token(
        access_key="test-ak",
        secret_key="test-sk",
        now=1_700_000_000,
    )
    header_raw, payload_raw, signature = token.split(".")

    assert signature
    assert _decode_base64url(header_raw) == {"alg": "HS256", "typ": "JWT"}
    assert _decode_base64url(payload_raw) == {
        "exp": 1_700_001_800,
        "iss": "test-ak",
        "nbf": 1_699_999_995,
    }


def test_build_kling_api_token_requires_access_key_and_secret_key() -> None:
    with pytest.raises(ValueError, match="Access Key / Secret Key"):
        build_kling_api_token(access_key="test-ak", secret_key="")
