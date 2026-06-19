#!/usr/bin/env python3
"""Login từng nick trong pool → cập nhật credit thật vào account_pool.json."""

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
    list_accounts,
    mark_account,
    min_reuse_credits,
    update_account_after_job,
)
from roboneo_web import RoboNeoError  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Refresh RoboNeo pool credits")
    parser.add_argument(
        "--include-locked",
        action="store_true",
        help="Thử cả nick locked (login lại)",
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Giây giữa mỗi nick")
    args = parser.parse_args()

    statuses = {"active", "depleted"}
    if args.include_locked:
        statuses.add("locked")

    rows = [a for a in list_accounts() if a.get("status") in statuses]
    print(f"📂 Pool: {_pool_path()} | {len(rows)} nick | min reuse {min_reuse_credits()} credit")

    ok = fail = 0
    for i, row in enumerate(rows, 1):
        email = (row.get("email") or "").strip()
        password = row.get("password") or ""
        if not email or not password:
            continue
        print(f"[{i}/{len(rows)}] {email} ({row.get('status')})…", end=" ", flush=True)
        try:
            _client, info = _login_once(email, password, rotate=False)
            cr = int(info.get("credits") or 0)
            update_account_after_job(email, cr)
            print(f"→ {cr} credit")
            ok += 1
        except RoboNeoError as e:
            mark_account(email, status="locked", note=str(e), credits=0)
            print(f"LOCK ({e})")
            fail += 1
        except Exception as e:
            mark_account(email, status="locked", note=str(e))
            print(f"ERR ({e})")
            fail += 1
        if args.delay > 0 and i < len(rows):
            time.sleep(args.delay)

    print(f"\n✅ Xong: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
