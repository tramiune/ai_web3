"""Giá Kling Motion Control — 0.6 coin/giây, tối đa 30s (làm tròn lên giây)."""

from __future__ import annotations

import math

from project_env import get_env, load_project_env

load_project_env()

KLING_COINS_PER_SEC = float(get_env("KLING_COINS_PER_SEC", "0.6"))
COIN_VND_RATE = int(get_env("COIN_VND_RATE", "1000"))
KLING_MIN_VIDEO_SEC = float(get_env("KLING_MIN_VIDEO_SEC", "3"))
KLING_MAX_VIDEO_SEC = float(get_env("KLING_MAX_VIDEO_SEC", "30"))


def billable_seconds(duration_sec: float | None) -> int:
    """Làm tròn lên giây, clamp 3–30 (khớp Kling + web)."""
    if duration_sec is None or duration_sec <= 0:
        return int(KLING_MIN_VIDEO_SEC)
    sec = int(math.ceil(float(duration_sec)))
    sec = max(int(KLING_MIN_VIDEO_SEC), min(int(KLING_MAX_VIDEO_SEC), sec))
    return sec


def cost_coins(duration_sec: float | None) -> float:
    sec = billable_seconds(duration_sec)
    raw = sec * KLING_COINS_PER_SEC
    return round(max(KLING_COINS_PER_SEC, raw), 1)


def cost_vnd(duration_sec: float | None) -> int:
    return int(round(cost_coins(duration_sec) * COIN_VND_RATE))
