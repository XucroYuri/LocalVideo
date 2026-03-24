from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoResult:
    """Result from video generation"""

    file_path: Path
    duration: float
    width: int
    height: int
    fps: int


@dataclass
class VideoProgress:
    """Progress update for video generation"""

    shot_index: int
    progress: int
    status: str
    message: str | None = None


class VideoProvider(ABC):
    """Base class for video generation providers"""

    name: str = "base_video"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        output_path: Path,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> VideoResult:
        """Generate video from prompt

        Args:
            prompt: Text description of video to generate
            output_path: Path to save generated video
            duration: Video duration in seconds
            width: Video width in pixels
            height: Video height in pixels
            fps: Frames per second
            resolution: Target resolution (e.g., 720/1080), provider-specific
            aspect_ratio: Target aspect ratio (e.g., "9:16"), provider-specific
            first_frame: Optional first frame image path
            last_frame: Optional last frame image path
            reference_images: Optional reference image list

        Returns:
            VideoResult with generation details
        """
        pass

    async def generate_batch(
        self,
        tasks: list[dict],
        output_dir: Path,
    ) -> AsyncIterator[VideoProgress]:
        """Generate multiple videos with progress updates

        Args:
            tasks: List of video generation tasks
            output_dir: Directory to save generated videos

        Yields:
            VideoProgress updates for each task
        """
        for i, task in enumerate(tasks):
            await self.generate(
                prompt=task["prompt"],
                output_path=output_dir / f"shot_{i:03d}.mp4",
                duration=task.get("duration"),
                width=task.get("width"),
                height=task.get("height"),
                fps=task.get("fps"),
                resolution=task.get("resolution"),
                aspect_ratio=task.get("aspect_ratio"),
                first_frame=task.get("first_frame"),
                last_frame=task.get("last_frame"),
                reference_images=task.get("reference_images"),
            )
            yield VideoProgress(
                shot_index=i,
                progress=100,
                status="completed",
            )
