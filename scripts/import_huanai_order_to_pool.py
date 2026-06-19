#!/usr/bin/env python3
"""Import nick từ lịch sử mua huanaihub (web login) vào account_pool.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from account_pool import _load_pool, _save_pool, list_accounts, upsert_account  # noqa: E402
from huanaihub import (  # noqa: E402
    _SESSION,
    _base_url,
    _credentials,
    _proxies,
    parse_roboneo_account,
)


def fetch_order_accounts(trans_id: str) -> list[tuple[str, str]]:
    base = _base_url()
    username, password = _credentials()
    proxies = _proxies()
    sess = requests.Session()
    sess.headers.update(_SESSION.headers)
    login = sess.post(
        f"{base}/ajaxs/client/login.php",
        data={"username": username, "password": password},
        timeout=30,
        proxies=proxies,
    )
    login.raise_for_status()
    body = login.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Login huanaihub fail: {body}")

    page = sess.get(f"{base}/client/order/{trans_id}", timeout=60, proxies=proxies)
    page.raise_for_status()
    match = re.search(r"<textarea[^>]*>(.*?)</textarea>", page.text, re.S | re.I)
    if not match:
        raise RuntimeError(f"Không tìm thấy danh sách nick trong đơn {trans_id}")

    raw = re.sub("<[^>]+>", "", match.group(1))
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(parse_roboneo_account(line))
    if not out:
        raise RuntimeError(f"Đơn {trans_id} không có nick")
    return out


def import_to_pool(
    accounts: list[tuple[str, str]],
    *,
    trans_id: str,
    default_credits: int | None = 120,
) -> tuple[int, int]:
    existing = {(a.get("email") or "").lower() for a in list_accounts()}
    added = skipped = 0
    for email, password in accounts:
        key = email.strip().lower()
        if key in existing:
            skipped += 1
            continue
        upsert_account(
            email,
            password,
            status="active",
            source="huanaihub",
            trans_id=trans_id,
            credits=default_credits,
        )
        existing.add(key)
        added += 1
    return added, skipped


def import_to_pool_file(
    pool_path: Path,
    accounts: list[tuple[str, str]],
    *,
    trans_id: str,
    default_credits: int | None = 120,
) -> tuple[int, int]:
    data = json.loads(pool_path.read_text(encoding="utf-8")) if pool_path.is_file() else {"accounts": []}
    existing = {(a.get("email") or "").lower() for a in data.get("accounts") or []}
    added = skipped = 0
    now = int(time.time())
    for email, password in accounts:
        key = email.strip().lower()
        if key in existing:
            skipped += 1
            continue
        row = {
            "email": key,
            "password": password,
            "status": "active",
            "source": "huanaihub",
            "trans_id": trans_id,
            "updated_at": now,
        }
        if default_credits is not None:
            row["credits"] = int(default_credits)
        data.setdefault("accounts", []).append(row)
        existing.add(key)
        added += 1
    _save_pool(data) if pool_path == ROOT / "account_pool.json" else pool_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Import nick huanaihub vào pool")
    parser.add_argument("--trans-id", required=True, help="Mã đơn huanaihub, vd VAYT1781882028")
    parser.add_argument(
        "--pool-file",
        default="",
        help="Đường dẫn pool (mặc định: account_pool.json trong project)",
    )
    parser.add_argument(
        "--no-credits",
        action="store_true",
        help="Không ghi credits=120 — để sync sau",
    )
    args = parser.parse_args()

    accounts = fetch_order_accounts(args.trans_id.strip())
    print(f"→ Lấy {len(accounts)} nick từ đơn {args.trans_id}")

    credits = None if args.no_credits else 120
    if args.pool_file:
        pool_path = Path(args.pool_file)
        added, skipped = import_to_pool_file(
            pool_path, accounts, trans_id=args.trans_id, default_credits=credits
        )
        total = len(json.loads(pool_path.read_text(encoding="utf-8")).get("accounts") or [])
        print(f"✅ Pool {pool_path}: +{added} mới, {skipped} đã có — tổng {total}")
    else:
        added, skipped = import_to_pool(
            accounts, trans_id=args.trans_id, default_credits=credits
        )
        print(f"✅ Pool local: +{added} mới, {skipped} đã có — tổng {len(list_accounts())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
