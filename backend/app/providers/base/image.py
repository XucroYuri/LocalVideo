from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

# Type alias for reference images list
ReferenceImages = list[Path]


@dataclass
class ImageResult:
    """Result from image generation"""

    file_path: Path
    width: int
    height: int


class ImageProvider(ABC):
    """Base class for image generation providers"""

    name: str = "base_image"
    supports_reference: bool = False

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int | None = None,
        height: int | None = None,
        reference_images: ReferenceImages | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> ImageResult:
        """Generate image from prompt

        Args:
            prompt: Text description of image to generate
            output_path: Path to save generated image
            width: Optional image width in pixels (provider-dependent)
            height: Optional image height in pixels (provider-dependent)
            reference_images: Optional list of reference image paths
            aspect_ratio: Optional aspect ratio string (e.g., "9:16", "1:1")
            image_size: Optional image size preset (e.g., "1K", "2K", "4K")

        Returns:
            ImageResult with generation details
        """
        pass
