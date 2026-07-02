"""Ưu đãi RoboNeo 24h cho nick Kaling mới (từ 00:00 19/06/2026 VN)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from project_env import get_env, load_project_env

load_project_env()

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh") if ZoneInfo else timezone(timedelta(hours=7))
TRIAL_START = datetime(2026, 6, 19, 0, 0, 0, tzinfo=VN_TZ)
TRIAL_WINDOW = timedelta(hours=24)
TRIAL_MODEL_ID = "130"
TRIAL_COST = 3
TRIAL_MAX_SEC = 12
KALING_ROBONEO_MODEL_IDS = frozenset({"124", "131", TRIAL_MODEL_ID})


def _parse_created_at(user_data: dict | None) -> datetime | None:
    if not user_data:
        return None
    ca = user_data.get("createdAt")
    if ca is None:
        return None
    if hasattr(ca, "timestamp"):
        return datetime.fromtimestamp(ca.timestamp(), tz=timezone.utc)
    if isinstance(ca, datetime):
        return ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
    if isinstance(ca, dict):
        sec = ca.get("_seconds", ca.get("seconds"))
        if sec is not None:
            return datetime.fromtimestamp(float(sec), tz=timezone.utc)
    return None


def is_roboneo_trial_eligible(
    user_data: dict | None,
    *,
    now: datetime | None = None,
) -> bool:
    created = _parse_created_at(user_data)
    if created is None:
        return False
    now = now or datetime.now(timezone.utc)
    start_utc = TRIAL_START.astimezone(timezone.utc)
    created_utc = created.astimezone(timezone.utc)
    if created_utc < start_utc:
        return False
    return now < created_utc + TRIAL_WINDOW


def is_roboneo_trial_order(order_data: dict | None) -> bool:
    if not order_data:
        return False
    if order_data.get("roboneoTrial") is True:
        return True
    return str(order_data.get("modelId") or "").strip() == TRIAL_MODEL_ID


def validate_roboneo_trial_order(
    user_data: dict | None,
    order_data: dict | None,
    *,
    duration_sec: float | None = None,
) -> tuple[bool, str]:
    if not is_roboneo_trial_order(order_data):
        return True, ""
    if str((order_data or {}).get("modelId") or "").strip() != TRIAL_MODEL_ID:
        return False, "modelId"
    try:
        cost = int((order_data or {}).get("costCoins") or 0)
    except (TypeError, ValueError):
        cost = 0
    if cost != TRIAL_COST:
        return False, "cost"
    if not is_roboneo_trial_eligible(user_data):
        return False, "expired"
    # ffmpeg trim (nhất là stream copy) có thể để metadata dài hơn chút (ví dụ 12.2s).
    # Cho phép dung sai rộng hơn để tránh false-negative cho đơn trial đã được cắt về 12s.
    if duration_sec is not None and duration_sec > TRIAL_MAX_SEC + 0.6:
        return False, "duration"
    return True, ""
