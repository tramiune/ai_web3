"""Chuẩn hoá / cắt video tham chiếu trên server (bot VPS có ffmpeg)."""

from __future__ import annotations

from pathlib import Path

from roboneo_trial import TRIAL_MAX_SEC, is_roboneo_trial_order
from tool98_api import probe_video_duration_seconds, trim_video_to_seconds
from videoaieasy_web import duration_for_order


def max_reference_video_sec_for_order(order_data: dict | None) -> float:
    """Giới hạn giây video motion theo gói — server cắt nếu upload dài hơn."""
    data = order_data or {}
    if is_roboneo_trial_order(data):
        return float(TRIAL_MAX_SEC)
    for key in ("maxVideoSec", "vaeDurationSec", "durationSec"):
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return float(duration_for_order(data))


def trim_reference_video_for_order(vid_path: str | Path, order_data: dict | None) -> str:
    """Cắt video tham chiếu về giới hạn gói nếu dài hơn (mobile upload không cắt được trên browser)."""
    path = Path(vid_path)
    max_sec = max_reference_video_sec_for_order(order_data)
    dur = probe_video_duration_seconds(str(path))
    if dur is None or dur <= max_sec + 0.15:
        return str(path)
    print(f"✂️ Server cắt video {dur:.1f}s → {max_sec:.0f}s")
    out = trim_video_to_seconds(path, max_seconds=max_sec)
    return str(out)
