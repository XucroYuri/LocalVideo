from copy import deepcopy

LLM_PROVIDER_TYPE_OPENAI_CHAT = "openai_chat"
LLM_PROVIDER_TYPE_OPENAI_RESPONSES = "openai_responses"
LLM_PROVIDER_TYPE_ANTHROPIC_MESSAGES = "anthropic_messages"
LLM_PROVIDER_TYPE_GEMINI = "gemini"

LLM_PROVIDER_TYPES = {
    LLM_PROVIDER_TYPE_OPENAI_CHAT,
    LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
    LLM_PROVIDER_TYPE_ANTHROPIC_MESSAGES,
    LLM_PROVIDER_TYPE_GEMINI,
}

BUILTIN_LLM_PROVIDERS = [
    {
        "id": "builtin_openai",
        "name": "OpenAI",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://api.openai.com",
        "api_key": "",
        "catalog_models": ["gpt-5.4", "gpt-5.4-pro"],
        "enabled_models": ["gpt-5.4", "gpt-5.4-pro"],
        "default_model": "gpt-5.4",
        "supports_vision": True,
    },
    {
        "id": "builtin_anthropic",
        "name": "Anthropic",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_ANTHROPIC_MESSAGES,
        "base_url": "https://api.anthropic.com",
        "api_key": "",
        "catalog_models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
        ],
        "enabled_models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
        ],
        "default_model": "claude-sonnet-4-6",
        "supports_vision": True,
    },
    {
        "id": "builtin_gemini",
        "name": "Gemini",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_GEMINI,
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "",
        "catalog_models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
        ],
        "enabled_models": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
        ],
        "default_model": "gemini-3.1-pro-preview",
        "supports_vision": True,
    },
    {
        "id": "builtin_deepseek",
        "name": "深度求索",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "catalog_models": ["deepseek-chat", "deepseek-reasoner"],
        "enabled_models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "supports_vision": False,
    },
    {
        "id": "builtin_minimax",
        "name": "minimax",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://api.minimaxi.com/v1",
        "api_key": "",
        "catalog_models": ["MiniMax-M2.5", "MiniMax-M2.7"],
        "enabled_models": ["MiniMax-M2.5", "MiniMax-M2.7"],
        "default_model": "MiniMax-M2.5",
        "supports_vision": False,
    },
    {
        "id": "builtin_zhipu",
        "name": "智谱开放平台",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "catalog_models": ["GLM-5"],
        "enabled_models": ["GLM-5"],
        "default_model": "GLM-5",
        "supports_vision": False,
    },
    {
        "id": "builtin_moonshot",
        "name": "月之暗面",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://api.moonshot.cn",
        "api_key": "",
        "catalog_models": ["kimi-k2.5"],
        "enabled_models": ["kimi-k2.5"],
        "default_model": "kimi-k2.5",
        "supports_vision": False,
    },
    {
        "id": "builtin_volcengine",
        "name": "火山引擎",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key": "",
        "catalog_models": ["doubao-seed-2-0-pro-260215"],
        "enabled_models": ["doubao-seed-2-0-pro-260215"],
        "default_model": "doubao-seed-2-0-pro-260215",
        "supports_vision": True,
    },
    {
        "id": "builtin_xiaomi_mimo",
        "name": "小米 MiMo",
        "is_builtin": True,
        "provider_type": LLM_PROVIDER_TYPE_OPENAI_CHAT,
        "base_url": "https://api.xiaomimimo.com/v1",
        "api_key": "",
        "catalog_models": ["mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"],
        "enabled_models": ["mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"],
        "default_model": "mimo-v2-pro",
        "supports_vision": True,
    },
]

BUILTIN_MINIMAX_LLM_PROVIDER_ID = "builtin_minimax"
BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID = "builtin_xiaomi_mimo"


def default_llm_providers() -> list[dict]:
    return deepcopy(BUILTIN_LLM_PROVIDERS)


def is_minimax_provider(
    provider_id: str | None = None,
    provider_name: str | None = None,
    base_url: str | None = None,
) -> bool:
    normalized_id = str(provider_id or "").strip().lower()
    normalized_name = str(provider_name or "").strip().lower()
    normalized_url = str(base_url or "").strip().lower()
    return (
        "minimax" in normalized_id
        or "minimax" in normalized_name
        or "minimaxi.com" in normalized_url
    )


def canonicalize_llm_model(
    model: str | None,
    *,
    provider_id: str | None = None,
    provider_name: str | None = None,
    base_url: str | None = None,
) -> str:
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return ""
    if not is_minimax_provider(provider_id, provider_name, base_url):
        return normalized_model
    return normalized_model
