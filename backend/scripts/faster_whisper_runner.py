from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _normalize_timestamp(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return parsed if parsed >= 0 else fallback


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


logger = logging.getLogger("faster_whisper_runner")


def _configure_file_logging(invocation_id: str) -> Path:
    log_dir = Path(__file__).resolve().parents[1] / "storage" / "logs" / "faster-whisper"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{invocation_id}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    return log_path


def _write_result_file(result_path: Path, payload: dict[str, Any]) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _transcribe(
    *,
    audio_path: Path,
    model_name: str,
    model_path: Path | None,
    device: str,
    compute_type: str,
) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("选定的本地模型 Python 环境未安装 faster-whisper。") from exc

    started = time.perf_counter()
    logger.info(
        "runner start audio=%s model=%s model_path=%s device=%s compute_type=%s",
        audio_path,
        model_name,
        model_path,
        device,
        compute_type,
    )
    model_source = str(model_path) if model_path is not None else model_name
    model = WhisperModel(model_source, device=device, compute_type=compute_type)
    segments_iter, _ = model.transcribe(str(audio_path), word_timestamps=True)

    payload_segments: list[dict[str, Any]] = []
    payload_words: list[dict[str, Any]] = []
    preview_tokens: list[str] = []

    for segment_index, segment in enumerate(segments_iter):
        seg_text = (getattr(segment, "text", "") or "").strip()
        seg_start = _normalize_timestamp(getattr(segment, "start", 0.0), 0.0)
        seg_end = _normalize_timestamp(getattr(segment, "end", seg_start + 0.01), seg_start + 0.01)
        if seg_end <= seg_start:
            seg_end = seg_start + 0.01

        segment_words: list[dict[str, Any]] = []
        for word in getattr(segment, "words", None) or []:
            word_text = (getattr(word, "word", "") or "").strip()
            if not word_text:
                continue
            word_start = _normalize_timestamp(getattr(word, "start", seg_start), seg_start)
            word_end = _normalize_timestamp(
                getattr(word, "end", word_start + 0.01), word_start + 0.01
            )
            if word_end <= word_start:
                word_end = word_start + 0.01
            payload = {
                "word": word_text,
                "start": word_start,
                "end": word_end,
                "segment_index": segment_index,
            }
            segment_words.append(payload)
            payload_words.append(payload)

        payload_segments.append(
            {
                "text": seg_text,
                "start": seg_start,
                "end": seg_end,
                "words": segment_words,
            }
        )
        if seg_text:
            preview_tokens.append(seg_text)
        _emit(
            {
                "type": "progress",
                "utterance_index": segment_index + 1,
                "utterance_end": seg_end,
            }
        )
    result = {
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "utterance_count": len(payload_segments),
        "word_count": len(payload_words),
        "preview_text": " ".join(preview_tokens).strip(),
        "utterances": payload_segments,
        "words": payload_words,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    logger.info(
        "runner done utterances=%s words=%s elapsed_ms=%s",
        result["utterance_count"],
        result["word_count"],
        result["elapsed_ms"],
    )
    return result


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-path", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-path", required=False)
    parser.add_argument("--device", required=True)
    parser.add_argument("--compute-type", required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--result-path", required=True)
    args = parser.parse_args()

    log_path = _configure_file_logging(str(args.invocation_id).strip())
    audio_path = Path(args.audio_path).expanduser()
    result_path = Path(args.result_path).expanduser()
    if not audio_path.exists() or not audio_path.is_file():
        print(f"音频文件不存在: {audio_path}", file=sys.stderr)
        return 1
    logger.info(
        "runner invocation_id=%s log_path=%s result_path=%s",
        args.invocation_id,
        log_path,
        result_path,
    )

    try:
        result = _transcribe(
            audio_path=audio_path,
            model_name=str(args.model_name).strip(),
            model_path=Path(args.model_path).expanduser() if args.model_path else None,
            device=str(args.device).strip(),
            compute_type=str(args.compute_type).strip(),
        )
    except Exception as exc:
        logger.exception("runner failed audio=%s", audio_path)
        print(str(exc), file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    _write_result_file(result_path, result)
    _emit(
        {
            "type": "result",
            "result_path": str(result_path),
            "utterance_count": result.get("utterance_count"),
            "word_count": result.get("word_count"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
