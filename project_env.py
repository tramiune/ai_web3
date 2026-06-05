"""Nạp biến từ .env vào os.environ (chuẩn hóa CRLF — tránh default\\r gây lỗi API)."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_LOADED = False

_ENV_PREFIXES = ("XIAOYANG_", "BOT_", "AIDANCING_", "R2_", "TELEGRAM_")


def _clean_val(val: str) -> str:
    return val.strip().strip("\r\n").strip('"').strip("'")


def _strip_polluted_os_environ() -> None:
    """Bash `source .env` với CRLF có thể set giá trị kèm \\r — gỡ trước khi gọi API."""
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES):
            os.environ[key] = _clean_val(os.environ[key])


def load_project_env(env_path: Path | None = None) -> None:
    global _LOADED
    if _LOADED:
        return
    _strip_polluted_os_environ()
    path = env_path or (_ROOT / ".env")
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ[key] = _clean_val(val)
    _strip_polluted_os_environ()
    _LOADED = True


def get_env(key: str, default: str = "") -> str:
    load_project_env()
    return _clean_val(os.environ.get(key, default))
