#!/usr/bin/env python3
"""Thống kê số dư nick VAE / XiaoYang / Aidancing — CLI hoặc sync Firestore admin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_balance_report import (  # noqa: E402
    collect_engine_balances,
    format_engine_balance_report,
    sync_engine_balances_to_firestore,
)
from project_env import get_env, load_project_env  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Thống kê số dư VAE / XY / Aidancing")
    parser.add_argument("--site", default="", help="Tên hiển thị (vd: Kaling)")
    parser.add_argument("--json", action="store_true", help="In JSON")
    parser.add_argument(
        "--sync-firestore",
        metavar="BOT_NAME",
        help="Ghi lên Firestore bots/BOT_NAME (admin panel)",
    )
    args = parser.parse_args()
    load_project_env()
    site = (args.site or get_env("SITE_NAME") or ROOT.name or "site").strip()

    if args.sync_firestore:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred_path = ROOT / "serviceAccountKey.json"
            firebase_admin.initialize_app(credentials.Certificate(str(cred_path)))
        data = sync_engine_balances_to_firestore(firestore.client(), args.sync_firestore)
        print(f"✅ Sync engineBalances → bots/{args.sync_firestore}")
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(format_engine_balance_report(site, data))
        return 0

    data = collect_engine_balances()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_engine_balance_report(site, data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
