# Import subpackages for provider registration side effects.
from . import audio as _audio
from . import deep_research as _deep_research
from . import image as _image
from . import llm as _llm
from . import search as _search
from . import video as _video
from .base import (
    AudioProvider,
    AudioResult,
    DeepResearchEvent,
    DeepResearchProvider,
    DeepResearchRateLimitError,
    DeepResearchResult,
    DeepResearchSource,
    DeepResearchTask,
    ImageProvider,
    ImageResult,
    LLMProvider,
    LLMResponse,
    SearchProvider,
    SearchResult,
    VideoProgress,
    VideoProvider,
    VideoResult,
)
from .registry import (
    audio_registry,
    deep_research_registry,
    get_audio_provider,
    get_deep_research_provider,
    get_image_provider,
    get_llm_provider,
    get_search_provider,
    get_video_provider,
    image_registry,
    llm_registry,
    search_registry,
    video_registry,
)

_REGISTERED_PROVIDER_MODULES = (
    _audio,
    _deep_research,
    _image,
    _llm,
    _search,
    _video,
)

__all__ = [
    "llm_registry",
    "search_registry",
    "deep_research_registry",
    "audio_registry",
    "image_registry",
    "video_registry",
    "get_llm_provider",
    "get_search_provider",
    "get_deep_research_provider",
    "get_audio_provider",
    "get_image_provider",
    "get_video_provider",
    "LLMProvider",
    "LLMResponse",
    "SearchProvider",
    "SearchResult",
    "DeepResearchProvider",
    "DeepResearchRateLimitError",
    "DeepResearchTask",
    "DeepResearchResult",
    "DeepResearchEvent",
    "DeepResearchSource",
    "AudioProvider",
    "AudioResult",
    "ImageProvider",
    "ImageResult",
    "VideoProvider",
    "VideoResult",
    "VideoProgress",
]
