from .edge_tts import EdgeTTSProvider
from .kling_tts import KlingTTSProvider
from .minimax_tts import MiniMaxTTSProvider
from .vidu_tts import ViduTTSProvider
from .volcengine_tts import VolcengineTTSProvider
from .wan2gp import Wan2GPAudioProvider
from .xiaomi_mimo_tts import XiaomiMiMoTTSProvider

__all__ = [
    "EdgeTTSProvider",
    "KlingTTSProvider",
    "MiniMaxTTSProvider",
    "ViduTTSProvider",
    "VolcengineTTSProvider",
    "Wan2GPAudioProvider",
    "XiaomiMiMoTTSProvider",
]
