#!/usr/bin/env python3
"""Login lại mọi nick VAE (VideoAiEasy) — chạy trên VPS Kaling khi session hết hạn."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from videoaieasy_web import VideoAiEasyClient, profile_credits
from xiaoyang_motion import load_videoaieasy_accounts


def main() -> int:
    accounts = load_videoaieasy_accounts()
    if not accounts:
        print("❌ Không có VIDEOAIEASY_ACCOUNTS trong .env")
        return 1
    ok = 0
    for acc in accounts:
        email = acc.get("email") or "?"
        aid = acc["id"]
        print(f"\n🔑 Login VAE: {email} ({aid})...")
        try:
            api = VideoAiEasyClient(account_id=aid)
            profile = api.ensure_session(acc["email"], acc.get("password"))
            coins = profile_credits(profile)
            print(f"   ✅ OK — {coins} coins")
            ok += 1
        except Exception as e:
            print(f"   ❌ {e}")
    print(f"\n{'=' * 40}\nKết quả: {ok}/{len(accounts)} nick VAE login OK")
    return 0 if ok == len(accounts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
