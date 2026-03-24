from app.providers.registry import video_registry

from .kling import KlingVideoProvider
from .minimax import MiniMaxVideoProvider
from .vertex_ai import VertexAIVideoProvider
from .vidu import ViduVideoProvider
from .volcengine_seedance import VolcengineSeedanceVideoProvider
from .wan2gp import Wan2GPVideoProvider

video_registry.register("volcengine_seedance", VolcengineSeedanceVideoProvider)
video_registry.register("vertex_ai", VertexAIVideoProvider)
video_registry.register("wan2gp", Wan2GPVideoProvider)
video_registry.register("kling", KlingVideoProvider)
video_registry.register("vidu", ViduVideoProvider)
video_registry.register("minimax", MiniMaxVideoProvider)
