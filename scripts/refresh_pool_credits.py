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
    _login_once,
    _pool_path,
    acquire_pool_sync_lock,
    get_or_refresh_client,
    list_accounts,
    mark_account,
    min_pick_credits,
    release_pool_sync_lock,
    update_account_after_job,
)
from roboneo_web import RoboNeoError, resolve_surface  # noqa: E402
from project_env import get_env  # noqa: E402


def _eligible_rows(*, sync_all: bool, include_locked: bool) -> list[dict]:
    rows = []
    for row in list_accounts():
        email = (row.get("email") or "").strip()
        password = row.get("password") or ""
        if not email or not password:
            continue
        if sync_all:
            rows.append(row)
            continue
        status = row.get("status") or "active"
        if status in ("active", "depleted") or (include_locked and status == "locked"):
            rows.append(row)
    return rows


def _sync_one(
    row: dict,
    *,
    surface: str,
    force_login: bool,
    index: int,
    total: int,
) -> tuple[bool, int | None]:
    email = (row.get("email") or "").strip()
    password = row.get("password") or ""
    status = row.get("status") or "?"
    print(f"[{index}/{total}] {email} ({status})…", end=" ", flush=True)
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
    except RoboNeoError as e:
        mark_account(email, status="locked", note=str(e), credits=0)
        print(f"LOCK ({e})")
        return False, None
    except Exception as e:
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
    parser.add_argument("--delay", type=float, default=0.0, help="Giây giữa mỗi nick")
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Không tạo .pool_sync.lock (chỉ dùng khi test)",
    )
    args = parser.parse_args()

    sync_all = bool(args.all)
    include_locked = bool(args.include_locked or sync_all)
    force_login = bool(args.force_login or sync_all)
    rows = _eligible_rows(sync_all=sync_all, include_locked=include_locked)
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
        f"force_login={force_login} | min pick {min_pick_credits()} credit"
    )

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
            )
            if success:
                ok += 1
                if cr is not None and cr >= min_pick_credits():
                    ge120 += 1
            else:
                fail += 1
            if args.delay > 0 and i < len(rows):
                time.sleep(args.delay)
    finally:
        if not args.no_lock and got_lock:
            release_pool_sync_lock()

    print(f"\n✅ Xong: ok={ok} fail={fail} | active≥{min_pick_credits()}: {ge120}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
