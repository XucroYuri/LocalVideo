from app.providers.registry import image_registry

from .gemini_api import GeminiAPIImageProvider
from .kling import KlingImageProvider
from .minimax import MiniMaxImageProvider
from .openai_chat import OpenAIChatImageProvider
from .vertex_ai import VertexAIImageProvider
from .vidu import ViduImageProvider
from .volcengine_seedream import VolcengineSeedreamImageProvider
from .wan2gp import Wan2GPImageProvider

image_registry.register("vertex_ai", VertexAIImageProvider)
image_registry.register("gemini_api", GeminiAPIImageProvider)
image_registry.register("wan2gp", Wan2GPImageProvider)
image_registry.register("volcengine_seedream", VolcengineSeedreamImageProvider)
image_registry.register("openai_chat", OpenAIChatImageProvider)
image_registry.register("kling", KlingImageProvider)
image_registry.register("vidu", ViduImageProvider)
image_registry.register("minimax", MiniMaxImageProvider)
