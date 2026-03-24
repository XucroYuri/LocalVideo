from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AudioResult:
    """Result from audio synthesis"""

    file_path: Path
    duration: float
    sample_rate: int = 24000
    source_file_path: Path | None = None


class AudioProvider(ABC):
    """Base class for TTS audio providers"""

    name: str = "base_audio"

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        """Synthesize speech from text

        Args:
            text: Text to synthesize
            output_path: Path to save audio file
            voice: Optional voice name/id
            rate: Optional speech rate
            **kwargs: Provider specific arguments

        Returns:
            AudioResult with synthesis details
        """
        pass

    @abstractmethod
    def list_voices(self) -> list[str]:
        """List available voices

        Returns:
            List of available voice names
        """
        pass
