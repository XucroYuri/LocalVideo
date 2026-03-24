from copy import deepcopy

IMAGE_PROVIDER_TYPE_OPENAI_CHAT = "openai_chat"
IMAGE_PROVIDER_TYPE_GEMINI_API = "gemini_api"
IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM = "volcengine_seedream"

IMAGE_PROVIDER_TYPES = {
    IMAGE_PROVIDER_TYPE_OPENAI_CHAT,
    IMAGE_PROVIDER_TYPE_GEMINI_API,
    IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM,
}

BUILTIN_IMAGE_PROVIDERS: list[dict] = [
    {
        "id": "builtin_gemini_api",
        "name": "Gemini API",
        "is_builtin": True,
        "provider_type": IMAGE_PROVIDER_TYPE_GEMINI_API,
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "",
        "catalog_models": [
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
        ],
        "enabled_models": [
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
        ],
        "default_model": "gemini-3-pro-image-preview",
        "reference_aspect_ratio": "1:1",
        "reference_size": "1K",
        "frame_aspect_ratio": "9:16",
        "frame_size": "1K",
    },
    {
        "id": "builtin_volcengine_seedream",
        "name": "Volcengine Seedream",
        "is_builtin": True,
        "provider_type": IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM,
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key": "",
        "catalog_models": [
            "doubao-seedream-5.0",
            "doubao-seedream-4.5",
            "doubao-seedream-4.0",
        ],
        "enabled_models": [
            "doubao-seedream-5.0",
            "doubao-seedream-4.5",
            "doubao-seedream-4.0",
        ],
        "default_model": "doubao-seedream-5.0",
        "reference_aspect_ratio": "1:1",
        "reference_size": "2K",
        "frame_aspect_ratio": "9:16",
        "frame_size": "2K",
    },
]


def default_image_providers() -> list[dict]:
    return deepcopy(BUILTIN_IMAGE_PROVIDERS)
