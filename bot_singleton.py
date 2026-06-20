"""Chặn nhiều process bot.py --name <cùng tên> trên một máy."""

from __future__ import annotations

import atexit
import fcntl
import os
import sys
from pathlib import Path

_lock_handle = None


def _safe_bot_name(bot_name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in bot_name)


def acquire_bot_instance_lock(bot_name: str) -> None:
    """Giữ file lock exclusive — instance thứ hai thoát ngay."""
    global _lock_handle
    if not bot_name:
        return

    run_dir = Path(os.environ.get("BOT_RUN_DIR", ".run"))
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / f"bot-{_safe_bot_name(bot_name)}.lock"

    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        other_pid = ""
        try:
            handle.seek(0)
            other_pid = handle.read().strip()
        except OSError:
            pass
        print(
            f"❌ Bot [{bot_name}] đã chạy (lock {lock_path}, pid={other_pid or '?'}). "
            "Chỉ được 1 instance — thoát."
        )
        sys.exit(1)

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    atexit.register(_release_lock, handle)


def _release_lock(handle) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass
