import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import edge_tts
from mutagen.mp3 import MP3

from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry

logger = logging.getLogger(__name__)


@audio_registry.register("edge_tts")
class EdgeTTSProvider(AudioProvider):
    DEFAULT_VOICE = "zh-CN-YunjianNeural"
    DEFAULT_RATE = "+0%"

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
    ):
        self.default_voice = voice
        self.default_rate = rate

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        del kwargs
        voice = voice or self.default_voice
        rate = rate or self.default_rate

        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(output_path))

        await self._trim_trailing_silence(output_path)
        duration = self._get_audio_duration(output_path)

        return AudioResult(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
        )

    def _get_audio_duration(self, file_path: Path) -> float:
        try:
            audio = MP3(str(file_path))
            return audio.info.length
        except Exception:
            return 0.0

    async def _trim_trailing_silence(self, file_path: Path) -> None:
        """Trim trailing silence to reduce long pauses at the end of TTS."""
        if not file_path.exists():
            return

        duration = self._get_audio_duration(file_path)
        if duration <= 0:
            return

        trim_end = await self._detect_trailing_silence_end(file_path, duration)
        if trim_end is None:
            return

        # Avoid trimming if the difference is negligible
        if duration - trim_end < 0.02:
            return

        tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=file_path.suffix)
        tmp_path = Path(tmp_path_str)
        Path(tmp_path_str).unlink(missing_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(file_path),
            "-t",
            f"{trim_end:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(tmp_path),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0 or not tmp_path.exists():
                error_text = stderr.decode(errors="ignore").strip()
                logger.warning("[EdgeTTS] Trim silence failed: %s", error_text)
                return
            shutil.move(str(tmp_path), str(file_path))
        except Exception as e:
            logger.warning("[EdgeTTS] Trim silence error: %s", e)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    async def _detect_trailing_silence_end(self, file_path: Path, duration: float) -> float | None:
        """Detect trailing silence end time using silencedetect."""
        # Tunable parameters for silence detection
        noise_db = "-38dB"
        min_silence = 0.2
        keep_tail = 0.06

        cmd = [
            "ffmpeg",
            "-i",
            str(file_path),
            "-af",
            f"silencedetect=noise={noise_db}:d={min_silence}",
            "-f",
            "null",
            "-",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            output = stderr.decode(errors="ignore")
        except Exception as e:
            logger.warning("[EdgeTTS] Silence detect error: %s", e)
            return None

        last_silence_start = None
        for line in output.splitlines():
            line = line.strip()
            if "silence_start:" in line:
                try:
                    last_silence_start = float(line.split("silence_start:")[-1].strip())
                except Exception:
                    continue

        if last_silence_start is None:
            return None

        # Only treat as trailing silence if it starts near the end
        if duration - last_silence_start < min_silence:
            return None

        trim_end = min(last_silence_start + keep_tail, duration)
        return trim_end

    def list_voices(self) -> list[str]:
        return [
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            "zh-CN-YunjianNeural",
            "zh-CN-YunxiNeural",
            "zh-CN-YunxiaNeural",
            "zh-CN-YunyangNeural",
            "zh-CN-liaoning-XiaobeiNeural",
            "zh-CN-shaanxi-XiaoniNeural",
            "zh-TW-HsiaoChenNeural",
            "zh-TW-YunJheNeural",
            "zh-TW-HsiaoYuNeural",
        ]

    async def list_voices_async(self) -> list[dict]:
        voices = await edge_tts.list_voices()
        return [dict(v) for v in voices if v.get("Locale", "").startswith("zh")]
