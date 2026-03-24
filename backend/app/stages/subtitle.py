import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import StageRuntimeError, StageValidationError
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.paths import get_output_dir, resolve_path_for_io
from app.stages.common.validators import is_compose_data_usable, is_storyboard_data_usable

from . import register_stage
from .base import StageHandler, StageResult

logger = logging.getLogger(__name__)

COMPOSE_DATA_REQUIRED_ERROR = "母版视频为空或不可用，请先执行母版合成"
STORYBOARD_DATA_REQUIRED_ERROR = "分镜数据为空或不可用，请先生成分镜"
MAX_CHARS_PER_LINE = 12
MIN_CHARS_PER_SENTENCE = 2
MAX_PAUSE_RATIO = 0.3
PAUSE_COMMA = 0.12
PAUSE_MEDIUM = 0.16
PAUSE_STRONG = 0.2
PUNCTUATION_PATTERN = re.compile(r"([，。！？；：,.!?;:、—…]+)")
PUNCTUATION_TO_REMOVE = re.compile(r"[，。！？；：,.!?;:、—…\"'()（）【】\[\]《》<>]")
TRAILING_PUNCTUATION_TO_REMOVE = re.compile(r"[，。！？；：,.!?;:、—…\s]+$")


def split_by_punctuation(text: str) -> list[str]:
    parts = PUNCTUATION_PATTERN.split(text)
    sentences: list[str] = []
    current = ""
    for part in parts:
        if PUNCTUATION_PATTERN.match(part):
            current += part
        else:
            if current.strip():
                sentences.append(current.strip())
            current = part
    if current.strip():
        sentences.append(current.strip())
    return [s for s in sentences if s]


def remove_punctuation(text: str) -> str:
    return PUNCTUATION_TO_REMOVE.sub("", text)


def strip_trailing_punctuation(text: str) -> str:
    return TRAILING_PUNCTUATION_TO_REMOVE.sub("", str(text or "").rstrip())


def merge_short_sentences(
    sentences: list[str], min_chars: int = MIN_CHARS_PER_SENTENCE
) -> list[str]:
    if min_chars <= 0:
        return sentences
    merged: list[str] = []
    i = 0
    while i < len(sentences):
        current = sentences[i].strip()
        if not current:
            i += 1
            continue
        if len(remove_punctuation(current)) < min_chars and i + 1 < len(sentences):
            sentences[i + 1] = (current + sentences[i + 1]).strip()
        else:
            merged.append(current)
        i += 1
    return merged


def get_sentence_pause(sentence: str) -> float:
    text = sentence.strip()
    if not text:
        return 0.0
    for ch in reversed(text):
        if ch in "。！？.!?":
            return PAUSE_STRONG
        if ch in "；：;:":
            return PAUSE_MEDIUM
        if ch in "，、,":
            return PAUSE_COMMA
        if ch in "—…":
            return PAUSE_MEDIUM
        if ch.isspace():
            continue
        break
    return 0.0


def wrap_subtitle_text(text: str, max_chars_per_line: int = MAX_CHARS_PER_LINE) -> str:
    text = text.strip()
    if len(text) <= max_chars_per_line:
        return text
    num_lines = (len(text) + max_chars_per_line - 1) // max_chars_per_line
    chars_per_line = (len(text) + num_lines - 1) // num_lines
    lines = []
    start = 0
    while start < len(text):
        end = min(start + chars_per_line, len(text))
        lines.append(text[start:end])
        start = end
    return "\n".join(lines)


def format_srt_time(seconds: float) -> str:
    value = max(0.0, float(seconds or 0.0))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    secs = int(value % 60)
    millis = int(round((value - int(value)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    if secs >= 60:
        minutes += 1
        secs -= 60
    if minutes >= 60:
        hours += 1
        minutes -= 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt_content(
    text: str, duration: float, max_chars: int = MAX_CHARS_PER_LINE
) -> tuple[str, int]:
    sentences = split_by_punctuation(text)
    sentences = merge_short_sentences(sentences, MIN_CHARS_PER_SENTENCE)
    if not sentences:
        sentences = [text]

    char_counts = [len(remove_punctuation(s)) for s in sentences]
    total_chars = sum(char_counts)
    if total_chars == 0:
        total_chars = len(sentences)
        char_counts = [1] * len(sentences)

    pauses = [get_sentence_pause(s) for s in sentences]
    if pauses:
        pauses[-1] = 0.0
    total_pause = sum(pauses)
    max_pause = duration * MAX_PAUSE_RATIO
    if total_pause > max_pause and total_pause > 0:
        scale = max_pause / total_pause
        pauses = [p * scale for p in pauses]
        total_pause = sum(pauses)

    available = max(duration - total_pause, 0.0)
    srt_entries: list[str] = []
    total_lines = 0
    current_time = 0.0
    block_index = 1
    for index, sentence in enumerate(sentences):
        sentence_duration = available * (char_counts[index] / total_chars)
        start_time = current_time
        end_time = min(current_time + sentence_duration, duration)
        display_text = strip_trailing_punctuation(sentence)
        if display_text:
            wrapped_text = wrap_subtitle_text(display_text, max_chars)
            total_lines += wrapped_text.count("\n") + 1
            srt_entries.append(f"{block_index}")
            srt_entries.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
            srt_entries.append(wrapped_text)
            srt_entries.append("")
            block_index += 1
        current_time = min(duration, end_time + pauses[index])

    for idx in range(len(srt_entries) - 1, -1, -1):
        if "-->" in srt_entries[idx]:
            start = srt_entries[idx].split(" --> ")[0]
            srt_entries[idx] = f"{start} --> {format_srt_time(duration)}"
            break
    return "\n".join(srt_entries), total_lines


@register_stage(StageType.SUBTITLE)
class SubtitleHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        if (input_data or {}).get("include_subtitle") is False:
            return StageResult(
                success=True,
                skipped=True,
                message="未启用字幕，已跳过",
            )

        compose_data = await self._get_compose_data(db, project)
        storyboard_data = await self._get_storyboard_data(db, project)
        if not compose_data:
            return StageResult(success=False, error=COMPOSE_DATA_REQUIRED_ERROR)
        if not storyboard_data:
            return StageResult(success=False, error=STORYBOARD_DATA_REQUIRED_ERROR)

        shots = self._build_shots(storyboard_data)
        if not shots:
            return StageResult(success=False, error=STORYBOARD_DATA_REQUIRED_ERROR)

        master_video_path = resolve_path_for_io(compose_data.get("master_video_path"))
        if master_video_path is None or not master_video_path.exists():
            return StageResult(success=False, error=COMPOSE_DATA_REQUIRED_ERROR)

        output_dir = self._get_output_dir(project)
        subtitle_dir = output_dir / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        subtitle_file_path = subtitle_dir / "final.srt"
        temp_audio_path = subtitle_dir / "_subtitle_audio.wav"

        try:
            await self._update_runtime_progress(db, stage, 5, "正在提取母版音轨...")
            total_duration = self._safe_float(compose_data.get("duration"))
            if total_duration <= 0:
                total_duration = await self._probe_media_duration(master_video_path)
            if total_duration <= 0:
                raise StageValidationError("无法获取母版视频时长，无法生成字幕")

            await self._extract_audio(master_video_path, temp_audio_path)

            async def on_progress(payload: dict[str, Any]) -> None:
                current_seconds = self._safe_float(payload.get("current_seconds"))
                progress = 10
                if total_duration > 0:
                    progress = 10 + int(min(60.0, (current_seconds / total_duration) * 60.0))
                phase = str(payload.get("phase") or "").strip() or "识别中"
                await self._update_runtime_progress(
                    db,
                    stage,
                    max(10, min(progress, 70)),
                    f"正在转写音频（{phase}）...",
                )

            from ._audio_split import _build_aligned_shot_bounds, transcribe_audio_words

            words = await transcribe_audio_words(temp_audio_path, on_progress=on_progress)
            if not words:
                raise StageRuntimeError("语音识别未返回有效词级时间戳，无法生成最终字幕。")

            await self._update_runtime_progress(db, stage, 78, "正在对齐台词与转写...")
            aligned_bounds = _build_aligned_shot_bounds(words, shots, total_duration)
            if not aligned_bounds:
                raise StageRuntimeError("最终字幕对齐失败，请检查台词与音频是否一致。")

            await self._update_runtime_progress(db, stage, 88, "正在生成字幕文件...")
            segments = self._build_segments(words, aligned_bounds, shots)
            if not segments:
                raise StageRuntimeError("未生成有效字幕片段。")

            srt_content = self._build_srt_content(segments)
            subtitle_file_path.write_text(srt_content, encoding="utf-8")

            transcript_text = self._build_transcript_text(words)
            corrected_text = "\n".join(
                str(shot.get("voice_content") or "").strip() for shot in shots if shot
            ).strip()
            line_count = sum(int(segment.get("line_count") or 0) for segment in segments)

            return StageResult(
                success=True,
                data={
                    "subtitle_file_path": str(subtitle_file_path),
                    "subtitle_format": "srt",
                    "duration": total_duration,
                    "line_count": line_count,
                    "track_language": "zh",
                    "correction_mode": "storyboard_align",
                    "transcript_text": transcript_text,
                    "corrected_text": corrected_text,
                    "segments": segments,
                    "updated_at": int(time.time()),
                },
            )
        except Exception as exc:
            return StageResult(success=False, error=str(exc))
        finally:
            if temp_audio_path.exists():
                temp_audio_path.unlink(missing_ok=True)

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        if not await self._get_compose_data(db, project):
            return COMPOSE_DATA_REQUIRED_ERROR
        if not await self._get_storyboard_data(db, project):
            return STORYBOARD_DATA_REQUIRED_ERROR
        return None

    def _build_segments(
        self,
        words: list[dict[str, Any]],
        aligned_bounds: list[dict[str, Any]],
        shots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        next_index = 1

        for shot_index, bound in enumerate(aligned_bounds):
            shot_start = self._safe_float(bound.get("start"))
            shot_end = max(shot_start + 0.01, self._safe_float(bound.get("end"), shot_start + 0.01))
            start_word = bound.get("start_word")
            end_word = bound.get("end_word")
            voice_content = str(shots[shot_index].get("voice_content") or "").strip()
            shot_segments = self._build_sentence_aligned_segments(
                words=words,
                shot_start=shot_start,
                shot_end=shot_end,
                start_word=int(start_word) if start_word is not None else None,
                end_word=int(end_word) if end_word is not None else None,
                original_text=voice_content,
            )
            for item in shot_segments:
                start = self._safe_float(item.get("start"))
                end = self._safe_float(item.get("end"))
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                line_count = text.count("\n") + 1
                segments.append(
                    {
                        "index": next_index,
                        "shot_index": shot_index,
                        "start": start,
                        "end": max(start + 0.01, end),
                        "text": text,
                        "line_count": line_count,
                    }
                )
                next_index += 1

        return segments

    def _build_sentence_aligned_segments(
        self,
        *,
        words: list[dict[str, Any]],
        shot_start: float,
        shot_end: float,
        start_word: int | None,
        end_word: int | None,
        original_text: str,
    ) -> list[dict[str, Any]]:
        if not original_text.strip():
            return []

        sentences = split_by_punctuation(original_text)
        sentences = merge_short_sentences(sentences, MIN_CHARS_PER_SENTENCE)
        if not sentences:
            sentences = [original_text.strip()]

        if start_word is None or end_word is None or end_word < start_word:
            return self._build_fallback_sentence_segments(
                shot_start=shot_start,
                shot_end=shot_end,
                original_text=original_text,
            )

        from ._audio_split import (
            _build_sequence_alignment_map,
            _normalize_match_text,
            _resolve_shot_match_span,
        )

        selected_words = [
            item
            for idx, item in enumerate(words)
            if start_word <= idx <= end_word and isinstance(item, dict)
        ]
        if not selected_words:
            return self._build_fallback_sentence_segments(
                shot_start=shot_start,
                shot_end=shot_end,
                original_text=original_text,
            )

        normalized_stream_parts: list[str] = []
        char_to_word_index: list[int] = []
        for word_index, item in enumerate(selected_words):
            normalized = str(item.get("normalized") or "")
            if not normalized:
                continue
            normalized_stream_parts.append(normalized)
            char_to_word_index.extend([word_index] * len(normalized))

        normalized_stream = "".join(normalized_stream_parts)
        normalized_sentences = [_normalize_match_text(sentence) for sentence in sentences]
        normalized_script = "".join(normalized_sentences)
        if not normalized_stream or not normalized_script or not char_to_word_index:
            return self._build_fallback_sentence_segments(
                shot_start=shot_start,
                shot_end=shot_end,
                original_text=original_text,
            )

        script_sentence_ranges: list[tuple[int, int]] = []
        cursor = 0
        for normalized_sentence in normalized_sentences:
            start = cursor
            cursor += len(normalized_sentence)
            script_sentence_ranges.append((start, cursor))

        char_mapping, _ = _build_sequence_alignment_map(normalized_script, normalized_stream)
        if not char_mapping:
            return self._build_fallback_sentence_segments(
                shot_start=shot_start,
                shot_end=shot_end,
                original_text=original_text,
            )

        raw_bounds: list[tuple[float, float]] = []
        for sentence_index, sentence in enumerate(sentences):
            normalized_sentence = normalized_sentences[sentence_index]
            if not normalized_sentence:
                raw_bounds.append((shot_start, shot_end))
                continue
            range_start, range_end = script_sentence_ranges[sentence_index]
            match_span = _resolve_shot_match_span(char_mapping, range_start, range_end)
            if match_span is None:
                logger.info(
                    "[Subtitle] sentence align fallback: shot=%s sentence=%s text=%s",
                    sentence_index,
                    sentence_index,
                    sentence,
                )
                return self._build_fallback_sentence_segments(
                    shot_start=shot_start,
                    shot_end=shot_end,
                    original_text=original_text,
                )

            match_start, match_end = match_span
            match_start = max(0, min(match_start, len(char_to_word_index) - 1))
            match_end = max(match_start, min(match_end, len(char_to_word_index) - 1))
            local_start_word = char_to_word_index[match_start]
            local_end_word = char_to_word_index[match_end]
            sentence_start = max(
                shot_start,
                self._safe_float(selected_words[local_start_word].get("start"), shot_start),
            )
            sentence_end = max(
                sentence_start + 0.01,
                self._safe_float(
                    selected_words[local_end_word].get("end"),
                    sentence_start + 0.01,
                ),
            )
            raw_bounds.append((sentence_start, min(sentence_end, shot_end)))

        segments: list[dict[str, Any]] = []
        previous_end = shot_start
        for sentence_index, sentence in enumerate(sentences):
            sentence_text = strip_trailing_punctuation(sentence)
            if not sentence_text:
                continue
            raw_start, raw_end = raw_bounds[sentence_index]
            segment_start = shot_start if sentence_index == 0 else max(previous_end, raw_start)
            if sentence_index == len(sentences) - 1:
                segment_end = shot_end
            else:
                segment_end = max(segment_start + 0.01, min(shot_end, raw_end))
            if segment_end <= segment_start:
                segment_end = min(shot_end, segment_start + 0.01)
            wrapped_text = wrap_subtitle_text(sentence_text, MAX_CHARS_PER_LINE)
            segments.append(
                {
                    "start": segment_start,
                    "end": segment_end,
                    "text": wrapped_text,
                }
            )
            previous_end = segment_end

        if segments:
            segments[-1]["end"] = shot_end
        return segments

    def _build_fallback_sentence_segments(
        self,
        *,
        shot_start: float,
        shot_end: float,
        original_text: str,
    ) -> list[dict[str, Any]]:
        shot_srt, _ = generate_srt_content(original_text, max(0.01, shot_end - shot_start))
        segments: list[dict[str, Any]] = []
        for item in self._parse_srt_entries(shot_srt):
            start = shot_start + self._safe_float(item.get("start"))
            end = shot_start + self._safe_float(item.get("end"))
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": start,
                    "end": max(start + 0.01, end),
                    "text": text,
                }
            )
        if segments:
            segments[-1]["end"] = shot_end
        return segments

    def _build_srt_content(self, segments: list[dict[str, Any]]) -> str:
        from ._audio_split import _format_srt_time

        entries: list[str] = []
        for index, segment in enumerate(segments, start=1):
            entries.append(str(index))
            entries.append(
                f"{_format_srt_time(self._safe_float(segment.get('start')))} --> "
                f"{_format_srt_time(self._safe_float(segment.get('end')))}"
            )
            entries.append(str(segment.get("text") or "").strip())
            entries.append("")
        return "\n".join(entries).strip() + "\n"

    def _parse_srt_entries(self, srt_content: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for raw_block in str(srt_content or "").strip().split("\n\n"):
            lines = [line.rstrip() for line in raw_block.splitlines() if line.strip()]
            if len(lines) < 3:
                continue
            timing_line = lines[1]
            if " --> " not in timing_line:
                continue
            start_text, end_text = timing_line.split(" --> ", maxsplit=1)
            entries.append(
                {
                    "start": self._parse_srt_time(start_text),
                    "end": self._parse_srt_time(end_text),
                    "text": "\n".join(lines[2:]).strip(),
                }
            )
        return entries

    def _parse_srt_time(self, value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        hours_text, minutes_text, rest = text.split(":", maxsplit=2)
        seconds_text, millis_text = rest.split(",", maxsplit=1)
        return (
            int(hours_text) * 3600
            + int(minutes_text) * 60
            + int(seconds_text)
            + int(millis_text) / 1000.0
        )

    def _build_transcript_text(self, words: list[dict[str, Any]]) -> str:
        from ._audio_split import _join_word_text

        text = ""
        for item in words:
            token = str(item.get("word") or "").strip()
            if not token:
                continue
            text = _join_word_text(text, token)
        return text.strip()

    def _build_shots(self, storyboard_data: dict[str, Any]) -> list[dict[str, Any]]:
        raw_shots = storyboard_data.get("shots")
        if not isinstance(raw_shots, list):
            return []
        shots: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_shots):
            if not isinstance(item, dict):
                continue
            shots.append(
                {
                    "shot_index": idx,
                    "voice_content": str(item.get("voice_content") or "").strip(),
                }
            )
        return shots

    async def _update_runtime_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        progress: int,
        message: str,
    ) -> None:
        stage.progress = max(0, min(99, int(progress)))
        output_data = dict(stage.output_data or {})
        output_data["progress_message"] = message
        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _extract_audio(self, video_path: Path, output_path: Path) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise StageRuntimeError(
                f"ffmpeg extract audio failed (code={process.returncode}): "
                f"{stderr.decode(errors='ignore').strip()}"
            )
        if not output_path.exists():
            raise StageRuntimeError("音轨提取完成但输出文件不存在")

    async def _probe_media_duration(self, media_path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return 0.0
        try:
            return max(0.0, float(stdout.decode(errors="ignore").strip() or 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def _get_compose_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.COMPOSE,
            usable_check=is_compose_data_usable,
        )

    async def _get_storyboard_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.STORYBOARD,
            usable_check=is_storyboard_data_usable,
        )

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
