#!/usr/bin/env python3
"""Login/sync toàn bộ pool RoboNeo — 2 nick/IP, cập nhật credit thật."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from account_pool import (  # noqa: E402
    _clear_current_ip_usage,
    _load_pool,
    _login_once,
    _pool_path,
    _save_pool,
    acquire_pool_sync_lock,
    get_or_refresh_client,
    is_proxy_error,
    list_accounts,
    mark_account,
    min_pick_credits,
    release_pool_sync_lock,
    rotate_proxy_for_retry,
    update_account_after_job,
)
from roboneo_web import RoboNeoError, resolve_surface  # noqa: E402
from project_env import get_env  # noqa: E402


def _eligible_rows(*, sync_all: bool, include_locked: bool, skip_locked: bool) -> list[dict]:
    rows = []
    for row in list_accounts():
        email = (row.get("email") or "").strip()
        password = row.get("password") or ""
        if not email or not password:
            continue
        status = row.get("status") or "active"
        if skip_locked and status == "locked":
            continue
        if sync_all:
            rows.append(row)
            continue
        if status in ("active", "depleted") or (include_locked and status == "locked"):
            rows.append(row)
    return rows


def _is_rate_limit(err: BaseException) -> bool:
    s = str(err or "").lower()
    return any(
        x in s
        for x in (
            "45130",
            "10115",
            "login limit",
            "too frequent",
            "operation too frequent",
        )
    )


def _sync_one(
    row: dict,
    *,
    surface: str,
    force_login: bool,
    index: int,
    total: int,
    rate_limit_pause: float,
    rate_limit_retries: int,
    proxy_retries: int,
) -> tuple[bool, int | None]:
    email = (row.get("email") or "").strip()
    password = row.get("password") or ""
    status = row.get("status") or "?"
    print(f"[{index}/{total}] {email} ({status})…", end=" ", flush=True)

    proxy_left = max(0, int(proxy_retries))
    rate_left = max(0, int(rate_limit_retries))

    while True:
        try:
            if force_login:
                _client, info = _login_once(email, password, rotate=False)
                cr = int(info.get("credits") or 0)
            else:
                _client, info = get_or_refresh_client(
                    email, password, force_sync=True, surface=surface
                )
                cr = int(info.get("credits") or 0)
            update_account_after_job(email, cr)
            tag = "active" if cr >= min_pick_credits() else "depleted"
            print(f"→ {cr} credit ({tag})")
            return True, cr
        except (RoboNeoError, Exception) as e:
            if is_proxy_error(e) and proxy_left > 0:
                proxy_left -= 1
                print(f"PROXY ({e}) — xoay IP, thử lại ({proxy_left} lần còn)…")
                rotate_proxy_for_retry()
                continue
            if _is_rate_limit(e) and rate_left > 0:
                rate_left -= 1
                print(
                    f"RATE ({e}) — chờ {int(rate_limit_pause)}s, xoay IP "
                    f"({rate_left} lần còn)…"
                )
                time.sleep(max(1.0, rate_limit_pause))
                rotate_proxy_for_retry()
                continue
            if is_proxy_error(e):
                print(f"SKIP proxy ({e})")
                return False, None
            if _is_rate_limit(e):
                print(f"SKIP rate-limit ({e})")
                return False, None
            if isinstance(e, RoboNeoError):
                mark_account(email, status="locked", note=str(e), credits=0)
                print(f"LOCK ({e})")
            else:
                mark_account(email, status="locked", note=str(e))
                print(f"ERR ({e})")
            return False, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh RoboNeo pool credits")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync toàn bộ nick có email/password trong pool",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Login lại từng nick (tuân 2 nick/IP trên pool)",
    )
    parser.add_argument(
        "--include-locked",
        action="store_true",
        help="Thử cả nick locked (mặc định bật khi --all)",
    )
    parser.add_argument("--delay", type=float, default=0.0, help="Giây nghỉ sau mỗi nick")
    parser.add_argument(
        "--rate-limit-pause",
        type=float,
        default=0.0,
        help="Giây chờ + xoay IP khi gặp 45130/10115 (khuyên 600)",
    )
    parser.add_argument(
        "--rate-limit-retries",
        type=int,
        default=2,
        help="Số lần thử lại mỗi nick khi rate-limit",
    )
    parser.add_argument(
        "--proxy-retries",
        type=int,
        default=3,
        help="Số lần xoay IP + thử lại khi proxy chết (Connection refused…)",
    )
    parser.add_argument(
        "--skip-locked",
        action="store_true",
        help="Bỏ qua nick status locked (dùng khi chạy lại sau batch fail)",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Không tạo .pool_sync.lock (chỉ dùng khi test)",
    )
    args = parser.parse_args()

    sync_all = bool(args.all)
    include_locked = bool(args.include_locked or sync_all)
    force_login = bool(args.force_login or sync_all)
    rows = _eligible_rows(
        sync_all=sync_all,
        include_locked=include_locked,
        skip_locked=bool(args.skip_locked),
    )
    surface = resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))

    if not rows:
        print("Không có nick để sync.")
        return 1

    got_lock = True
    if not args.no_lock:
        got_lock = acquire_pool_sync_lock()
        if not got_lock:
            print("⚠️ Pool sync khác đang chạy (.pool_sync.lock). Thoát.")
            return 2

    print(
        f"📂 Pool: {_pool_path()} | {len(rows)} nick | "
        f"force_login={force_login} | min pick {min_pick_credits()} credit | "
        f"delay={args.delay}s | rate_pause={args.rate_limit_pause}s | "
        f"proxy_retries={args.proxy_retries}"
    )

    if force_login:
        data = _load_pool()
        _clear_current_ip_usage(data)
        data["last_proxy_rotate_at"] = 0
        _save_pool(data)
        print("🔄 Xoay IP trước batch sync (2 nick/IP)…")
        rotate_proxy_for_retry()

    ok = fail = 0
    ge120 = 0
    try:
        for i, row in enumerate(rows, 1):
            success, cr = _sync_one(
                row,
                surface=surface,
                force_login=force_login,
                index=i,
                total=len(rows),
                rate_limit_pause=float(args.rate_limit_pause),
                rate_limit_retries=int(args.rate_limit_retries),
                proxy_retries=int(args.proxy_retries),
            )
            if success:
                ok += 1
                if cr is not None and cr >= min_pick_credits():
                    ge120 += 1
            else:
                fail += 1
            if i < len(rows):
                delay = float(args.delay)
                if delay > 0:
                    time.sleep(delay)
    finally:
        if not args.no_lock and got_lock:
            release_pool_sync_lock()

    print(f"\n✅ Xong: ok={ok} fail={fail} | active≥{min_pick_credits()}: {ge120}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
