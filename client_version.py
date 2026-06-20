"""Phiên bản client web — bot từ chối đơn từ bản cũ (cache)."""

from __future__ import annotations

from project_env import get_env, load_project_env

load_project_env()

# Bump khi deploy frontend breaking — đồng bộ với public/app-version.js
APP_CLIENT_VERSION = 15


def _parse_version(value) -> tuple[int, ...]:
    if value is None:
        return (0,)
    s = str(value).strip()
    if not s:
        return (0,)
    parts: list[int] = []
    for piece in s.replace("-", ".").split("."):
        piece = piece.strip()
        if not piece:
            continue
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def min_client_version() -> int:
    raw = get_env("MIN_CLIENT_VERSION", str(APP_CLIENT_VERSION))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return APP_CLIENT_VERSION


def client_version_ok(order_data: dict | None) -> bool:
    got = _parse_version((order_data or {}).get("clientVersion"))
    required = _parse_version(min_client_version())
    n = max(len(got), len(required))
    got_p = got + (0,) * (n - len(got))
    req_p = required + (0,) * (n - len(required))
    return got_p >= req_p


def client_version_label(order_data: dict | None) -> str:
    v = (order_data or {}).get("clientVersion")
    return str(v).strip() if v is not None and str(v).strip() else "none"
