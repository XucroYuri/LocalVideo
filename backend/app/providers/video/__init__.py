from app.providers.registry import video_registry

from .volcengine_seedance import VolcengineSeedanceVideoProvider
from .wan2gp import Wan2GPVideoProvider

video_registry.register("volcengine_seedance", VolcengineSeedanceVideoProvider)
video_registry.register("wan2gp", Wan2GPVideoProvider)
