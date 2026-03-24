from __future__ import annotations

import logging
import os
import signal
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

WAN2GP_RUNTIME_SETTINGS_MARKERS = (
    "_settings_img_",
    "_settings_img_batch_",
    "_settings_vid_",
    "_settings_aud_",
    "_settings_aud_batch_",
)

_ACTIVE_WAN2GP_PIDS: set[int] = set()
_ACTIVE_WAN2GP_PID_LOCK = threading.Lock()


def register_wan2gp_pid(pid: int) -> None:
    if pid <= 0:
        return
    with _ACTIVE_WAN2GP_PID_LOCK:
        _ACTIVE_WAN2GP_PIDS.add(pid)


def unregister_wan2gp_pid(pid: int) -> None:
    if pid <= 0:
        return
    with _ACTIVE_WAN2GP_PID_LOCK:
        _ACTIVE_WAN2GP_PIDS.discard(pid)


def _snapshot_registered_wan2gp_pids() -> set[int]:
    with _ACTIVE_WAN2GP_PID_LOCK:
        return set(_ACTIVE_WAN2GP_PIDS)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _looks_like_localvideo_wan2gp_worker(cmdline: str) -> bool:
    text = (cmdline or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "wgp.py" not in lowered or "--process" not in lowered:
        return False
    return any(marker in text for marker in WAN2GP_RUNTIME_SETTINGS_MARKERS)


def _looks_like_external_wan2gp_ui(cmdline: str) -> bool:
    text = (cmdline or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return "wgp.py" in lowered and "--process" not in lowered


def _read_proc_cmdline(pid: int) -> str:
    if pid <= 0:
        return ""
    cmdline_path = Path("/proc") / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except Exception:
        return ""
    if not raw:
        return ""
    parts = [p for p in raw.split(b"\x00") if p]
    return " ".join(part.decode("utf-8", errors="ignore") for part in parts)


def _scan_orphan_wan2gp_worker_pids() -> set[int]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return set()

    current_pid = os.getpid()
    detected: set[int] = set()
    for pid_dir in proc_root.glob("[0-9]*"):
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        cmdline = _read_proc_cmdline(pid)
        if not cmdline:
            continue
        if _looks_like_localvideo_wan2gp_worker(cmdline):
            detected.add(pid)
    return detected


def detect_external_wan2gp_ui_processes() -> list[tuple[int, str]]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []

    current_pid = os.getpid()
    detected: list[tuple[int, str]] = []
    for pid_dir in proc_root.glob("[0-9]*"):
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        if pid == current_pid or pid in _snapshot_registered_wan2gp_pids():
            continue
        cmdline = _read_proc_cmdline(pid)
        if not cmdline or not _looks_like_external_wan2gp_ui(cmdline):
            continue
        detected.append((pid, cmdline))
    detected.sort(key=lambda item: item[0])
    return detected


def terminate_pid_tree(pid: int, grace_seconds: float = 2.0) -> bool:
    if pid <= 0:
        return False

    alive = _process_exists(pid)
    if not alive:
        unregister_wan2gp_pid(pid)
        return False

    pgid: int | None = None
    current_pgid: int | None = None
    if hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(pid)
            current_pgid = os.getpgid(os.getpid())
        except Exception:
            pgid = None
            current_pgid = None
    if pgid is not None and current_pgid is not None and pgid == current_pgid:
        pgid = None

    term_sent = False
    if pgid is not None and hasattr(os, "killpg"):
        try:
            os.killpg(pgid, signal.SIGTERM)
            term_sent = True
        except ProcessLookupError:
            pass
        except Exception:
            logger.exception("[Wan2GP Cleanup] Failed to SIGTERM process group %s", pgid)
    if not term_sent:
        try:
            os.kill(pid, signal.SIGTERM)
            term_sent = True
        except ProcessLookupError:
            pass
        except Exception:
            logger.exception("[Wan2GP Cleanup] Failed to SIGTERM pid %s", pid)

    deadline = time.time() + max(0.2, grace_seconds)
    while time.time() < deadline:
        if not _process_exists(pid):
            break
        time.sleep(0.1)

    if _process_exists(pid):
        if pgid is not None and hasattr(os, "killpg"):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                logger.exception("[Wan2GP Cleanup] Failed to SIGKILL process group %s", pgid)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                logger.exception("[Wan2GP Cleanup] Failed to SIGKILL pid %s", pid)

    unregister_wan2gp_pid(pid)
    return True


def cleanup_wan2gp_runtime_processes(grace_seconds: float = 2.0) -> int:
    target_pids = _snapshot_registered_wan2gp_pids() | _scan_orphan_wan2gp_worker_pids()
    if not target_pids:
        return 0

    cleaned = 0
    for pid in sorted(target_pids):
        if terminate_pid_tree(pid, grace_seconds=grace_seconds):
            cleaned += 1
    if cleaned:
        logger.info("[Wan2GP Cleanup] Released %d lingering subprocess(es)", cleaned)
    return cleaned
