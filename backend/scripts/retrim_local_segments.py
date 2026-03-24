#!/usr/bin/env python3
"""Rebuild stitched segment inputs from raw segment wav files.

This script mirrors the current Wan2GP local anchor trim strategy:
- Anchor boundary by silence gap first.
- Fallback to estimated anchor-duration trimming.
- Final trailing-silence normalization.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

WAN2GP_SILENCEDETECT_NOISE_DB = -38.0
WAN2GP_SILENCEDETECT_MIN_SECONDS = 0.06
WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS = 0.08
WAN2GP_TARGET_TAIL_SILENCE_MS = 90
WAN2GP_MAX_TAIL_SILENCE_MS = 220

WAN2GP_LOCAL_ANCHOR_TEXT = "这里是收尾锚点"
WAN2GP_LOCAL_ANCHOR_PREFIX = "。"
WAN2GP_LOCAL_ANCHOR_SUFFIX = "。"
WAN2GP_LOCAL_ANCHOR_EXTRA_MARGIN_MS = 80
WAN2GP_LOCAL_ANCHOR_MIN_REMOVE_MS = 400
WAN2GP_LOCAL_ANCHOR_MAX_REMOVE_MS = 4500
WAN2GP_LOCAL_ANCHOR_GAP_DETECT_MIN_SECONDS = 0.03
WAN2GP_LOCAL_ANCHOR_BOUNDARY_MIN_GAP_SECONDS = 0.10
WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MIN_SECONDS = 1.2
WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MAX_SECONDS = 7.0
WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MULTIPLIER = 2.2


@dataclass
class SegmentReport:
    index: int
    raw_file: str
    stitched_file: str
    anchor_applied: bool
    anchor_trim_reason: str
    anchor_boundary_gap_seconds: float
    anchor_search_from_seconds: float
    pre_duration_seconds: float
    keep_until_seconds: float
    trailing_ms_after_trim: int


def _run_command(cmd: list[str]) -> tuple[int, str, str]:
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    return process.returncode, process.stdout, process.stderr


def _to_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _estimate_total_seconds_from_text(text: str) -> int:
    compact = re.sub(r"\s+", "", text or "")
    return max(1, (len(compact) + 3) // 4)


def _probe_audio_duration_seconds(file_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=duration:format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    return_code, stdout, _stderr = _run_command(cmd)
    if return_code != 0:
        return 0.0
    payload = json.loads(stdout or "{}")
    streams = payload.get("streams") or []
    stream0 = streams[0] if isinstance(streams, list) and streams else {}
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration = _to_float(stream0.get("duration"), 0.0)
    if duration <= 0:
        duration = _to_float(format_info.get("duration"), 0.0)
    return max(0.0, duration)


def _detect_silence_intervals(
    file_path: Path,
    *,
    detection_min_seconds: float,
) -> tuple[float, list[tuple[float, float]]]:
    duration = _probe_audio_duration_seconds(file_path)
    if duration <= 0:
        return 0.0, []
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(file_path),
        "-af",
        (
            "silencedetect="
            f"noise={WAN2GP_SILENCEDETECT_NOISE_DB:.1f}dB:"
            f"d={max(0.001, float(detection_min_seconds)):.3f}"
        ),
        "-f",
        "null",
        "-",
    ]
    return_code, _stdout, stderr = _run_command(cmd)
    if return_code not in {0, 255}:
        return duration, []

    start_pattern = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
    end_pattern = re.compile(
        r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*([0-9]+(?:\.[0-9]+)?)"
    )
    intervals: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        start_match = start_pattern.search(line)
        if start_match:
            pending_start = _to_float(start_match.group(1), 0.0)
            continue
        end_match = end_pattern.search(line)
        if end_match:
            end_value = _to_float(end_match.group(1), 0.0)
            if pending_start is not None and end_value > pending_start:
                intervals.append((pending_start, end_value))
            pending_start = None
    if pending_start is not None and duration > pending_start:
        intervals.append((pending_start, duration))
    return duration, intervals


def _detect_trailing_silence(file_path: Path) -> tuple[float, float]:
    duration, intervals = _detect_silence_intervals(
        file_path,
        detection_min_seconds=WAN2GP_SILENCEDETECT_MIN_SECONDS,
    )
    if not intervals:
        return duration, 0.0
    last_start, last_end = intervals[-1]
    if last_end < duration - WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS:
        return duration, 0.0
    trailing = max(0.0, duration - max(0.0, last_start))
    if trailing < WAN2GP_SILENCEDETECT_MIN_SECONDS:
        return duration, 0.0
    return duration, trailing


def _trim_audio_to_duration(input_path: Path, output_path: Path, end_seconds: float) -> None:
    safe_end = max(0.01, float(end_seconds))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-af",
        f"atrim=0:{safe_end:.6f},asetpts=N/SR/TB",
        "-vn",
        str(output_path),
    ]
    return_code, _stdout, stderr = _run_command(cmd)
    if return_code != 0 or not output_path.exists():
        raise RuntimeError(
            f"Trim failed: input={input_path} end={safe_end:.3f}s error={stderr.strip()}"
        )


def _estimate_anchor_trim_seconds(
    *,
    anchor_duration_seconds: float,
    trailing_silence_seconds: float,
) -> float:
    remove_ms = int(
        round(anchor_duration_seconds * 1000.0)
        + round(max(0.0, trailing_silence_seconds) * 1000.0)
        + WAN2GP_LOCAL_ANCHOR_EXTRA_MARGIN_MS
    )
    remove_ms = max(WAN2GP_LOCAL_ANCHOR_MIN_REMOVE_MS, remove_ms)
    remove_ms = min(WAN2GP_LOCAL_ANCHOR_MAX_REMOVE_MS, remove_ms)
    return float(remove_ms) / 1000.0


def _find_anchor_boundary_by_silence(
    *,
    file_path: Path,
    anchor_duration_seconds: float,
) -> tuple[float, float | None, float, float]:
    duration, intervals = _detect_silence_intervals(
        file_path,
        detection_min_seconds=WAN2GP_LOCAL_ANCHOR_GAP_DETECT_MIN_SECONDS,
    )
    if duration <= 0:
        return 0.0, None, 0.0, 0.0

    search_window_seconds = max(
        WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MIN_SECONDS,
        float(anchor_duration_seconds) * WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MULTIPLIER,
    )
    search_window_seconds = min(
        WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_WINDOW_MAX_SECONDS,
        search_window_seconds,
    )
    search_start = max(0.0, duration - search_window_seconds)

    candidates: list[tuple[float, float, float]] = []
    fallback_candidates: list[tuple[float, float, float]] = []
    for interval_start, interval_end in intervals:
        if interval_end <= interval_start:
            continue
        if interval_end >= duration - WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS:
            continue
        if interval_end < search_start:
            continue
        gap_seconds = interval_end - interval_start
        candidate = (interval_start, interval_end, gap_seconds)
        fallback_candidates.append(candidate)
        if gap_seconds >= WAN2GP_LOCAL_ANCHOR_BOUNDARY_MIN_GAP_SECONDS:
            candidates.append(candidate)

    if not candidates:
        candidates = fallback_candidates
    if not candidates:
        return duration, None, search_start, 0.0

    best_start, _best_end, best_gap = max(candidates, key=lambda item: (item[2], item[0]))
    trim_to_seconds = max(0.05, min(duration - 0.01, best_start))
    return duration, trim_to_seconds, search_start, best_gap


def _resolve_raw_files(raw_segments_dir: Path) -> list[Path]:
    files = sorted(raw_segments_dir.glob("segment_*_raw.wav"))
    if files:
        return files
    return sorted(raw_segments_dir.glob("segment_*_raw.*"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-trim raw segment wavs into stitched inputs.")
    parser.add_argument(
        "--artifacts-dir",
        required=True,
        help="Directory containing raw_segments/ and stitched_inputs/.",
    )
    parser.add_argument(
        "--anchor-duration-seconds",
        type=float,
        default=0.0,
        help="Override anchor reference duration in seconds. <=0 means auto estimate.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned trims without writing files.",
    )
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir).expanduser().resolve()
    raw_segments_dir = artifacts_dir / "raw_segments"
    stitched_inputs_dir = artifacts_dir / "stitched_inputs"
    if not raw_segments_dir.exists():
        raise FileNotFoundError(f"Missing raw_segments dir: {raw_segments_dir}")
    stitched_inputs_dir.mkdir(parents=True, exist_ok=True)

    raw_files = _resolve_raw_files(raw_segments_dir)
    if not raw_files:
        raise FileNotFoundError(f"No segment_*_raw files in: {raw_segments_dir}")

    anchor_enabled = len(raw_files) > 1
    anchor_duration_seconds = float(args.anchor_duration_seconds or 0.0)
    if anchor_enabled and anchor_duration_seconds <= 0:
        anchor_duration_seconds = float(
            _estimate_total_seconds_from_text(
                f"{WAN2GP_LOCAL_ANCHOR_PREFIX}{WAN2GP_LOCAL_ANCHOR_TEXT}{WAN2GP_LOCAL_ANCHOR_SUFFIX}"
            )
        )

    reports: list[SegmentReport] = []
    with tempfile.TemporaryDirectory(prefix="retrim_local_segments_") as tmp_dir_text:
        tmp_dir = Path(tmp_dir_text)
        for idx, raw_file in enumerate(raw_files):
            effective_path = raw_file
            segment_no = idx + 1
            pre_duration_seconds = _probe_audio_duration_seconds(raw_file)
            trim_to_seconds = pre_duration_seconds
            anchor_trim_reason = "none"
            boundary_gap_seconds = 0.0
            boundary_search_from_seconds = 0.0

            if anchor_enabled and idx < len(raw_files) - 1:
                (
                    pre_duration_seconds,
                    boundary_trim_to_seconds,
                    boundary_search_from_seconds,
                    boundary_gap_seconds,
                ) = _find_anchor_boundary_by_silence(
                    file_path=effective_path,
                    anchor_duration_seconds=anchor_duration_seconds,
                )
                if boundary_trim_to_seconds is None:
                    pre_duration_seconds, pre_trailing_seconds = _detect_trailing_silence(
                        effective_path
                    )
                    anchor_trim_seconds = _estimate_anchor_trim_seconds(
                        anchor_duration_seconds=anchor_duration_seconds,
                        trailing_silence_seconds=pre_trailing_seconds,
                    )
                    trim_to_seconds = max(0.05, pre_duration_seconds - anchor_trim_seconds)
                    anchor_trim_reason = "fallback_estimated"
                else:
                    trim_to_seconds = boundary_trim_to_seconds
                    anchor_trim_reason = "gap"

                if trim_to_seconds < pre_duration_seconds and not args.dry_run:
                    anchor_trimmed_path = tmp_dir / f"{raw_file.stem}.anchortrim{raw_file.suffix}"
                    _trim_audio_to_duration(effective_path, anchor_trimmed_path, trim_to_seconds)
                    effective_path = anchor_trimmed_path

            trailing_ms_after_trim = 0
            duration_after_anchor, trailing_seconds = _detect_trailing_silence(effective_path)
            trailing_ms = int(round(trailing_seconds * 1000.0))
            if duration_after_anchor > 0 and trailing_ms > WAN2GP_MAX_TAIL_SILENCE_MS:
                trim_seconds = max(
                    0.01,
                    duration_after_anchor
                    - ((trailing_ms - WAN2GP_TARGET_TAIL_SILENCE_MS) / 1000.0),
                )
                if not args.dry_run:
                    tail_trimmed_path = tmp_dir / f"{raw_file.stem}.tailtrim{raw_file.suffix}"
                    _trim_audio_to_duration(effective_path, tail_trimmed_path, trim_seconds)
                    effective_path = tail_trimmed_path
                trailing_ms_after_trim = WAN2GP_TARGET_TAIL_SILENCE_MS
            else:
                trailing_ms_after_trim = trailing_ms

            stitched_name = f"segment_{segment_no:03d}_stitched{raw_file.suffix.lower()}"
            stitched_path = stitched_inputs_dir / stitched_name
            if not args.dry_run:
                if stitched_path.exists():
                    stitched_path.unlink()
                shutil.copy2(str(effective_path), str(stitched_path))

            reports.append(
                SegmentReport(
                    index=segment_no,
                    raw_file=str(raw_file),
                    stitched_file=str(stitched_path),
                    anchor_applied=bool(anchor_enabled and idx < len(raw_files) - 1),
                    anchor_trim_reason=anchor_trim_reason,
                    anchor_boundary_gap_seconds=round(boundary_gap_seconds, 4),
                    anchor_search_from_seconds=round(boundary_search_from_seconds, 4),
                    pre_duration_seconds=round(pre_duration_seconds, 4),
                    keep_until_seconds=round(trim_to_seconds, 4),
                    trailing_ms_after_trim=int(trailing_ms_after_trim),
                )
            )

            print(
                f"[retrim] segment={segment_no:03d} reason={anchor_trim_reason} "
                f"keep_until={trim_to_seconds:.3f}s gap={boundary_gap_seconds:.3f}s "
                f"trailing={trailing_ms_after_trim}ms out={stitched_path}"
            )

    report_payload = {
        "artifacts_dir": str(artifacts_dir),
        "raw_segments_dir": str(raw_segments_dir),
        "stitched_inputs_dir": str(stitched_inputs_dir),
        "anchor_enabled": anchor_enabled,
        "anchor_duration_seconds": anchor_duration_seconds,
        "segments": [asdict(item) for item in reports],
    }
    report_path = stitched_inputs_dir / "retrim_report.json"
    if not args.dry_run:
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"[retrim] report={report_path}")


if __name__ == "__main__":
    main()
