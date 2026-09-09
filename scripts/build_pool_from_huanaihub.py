#!/usr/bin/env python3
"""Tải đơn huanaihub → tạo account_pool.json mới (active, credits=120)."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from huanaihub import parse_roboneo_account  # noqa: E402
from project_env import get_env, load_project_env  # noqa: E402


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://huanaihub.com/",
        }
    )
    return s


def login(s: requests.Session) -> str:
    load_project_env()
    username = (get_env("HUANAIHUB_USERNAME") or get_env("HUANAIHUB_EMAIL") or "").strip()
    password = (get_env("HUANAIHUB_PASSWORD") or get_env("HUANAIHUB_API_KEY") or "").strip()
    if not username or not password:
        raise RuntimeError("Thiếu HUANAIHUB_USERNAME + HUANAIHUB_PASSWORD trong .env")

    r = s.post(
        "https://huanaihub.com/ajaxs/client/login.php",
        data={"username": username, "password": password},
        timeout=60,
    )
    if r.status_code == 403:
        raise RuntimeError("huanaihub 403 — thử VPS/VPN VN")
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Login fail: {data.get('msg') or data}")
    print(f"✅ Login OK — {username}")
    return username


def _client_token(s: requests.Session) -> str:
    for url in (
        "https://huanaihub.com/client/orders",
        "https://huanaihub.com/client/home",
        "https://huanaihub.com/client/order",
    ):
        r = s.get(url, timeout=60)
        r.raise_for_status()
        patterns = [
            r"downloadFile\s*\(\s*[`'\"][^`'\"]+[`'\"]\s*,\s*[`'\"]([a-f0-9]{32,})[`'\"]",
            r"token['\"]\s*:\s*['\"]([a-f0-9]{32,})['\"]",
            r'name=["\']token["\']\s+value=["\']([a-f0-9]{32,})["\']',
            r'value=["\']([a-f0-9]{32,})["\']\s+name=["\']token["\']',
            r'data-token=["\']([a-f0-9]{32,})["\']',
            r'csrf[_-]?token["\']?\s*[:=]\s*["\']([a-f0-9]{32,})["\']',
        ]
        for pat in patterns:
            m = re.search(pat, r.text, re.I)
            if m:
                return m.group(1)
    raise RuntimeError("Không tìm thấy client token trên huanaihub client pages")


def list_orders(s: requests.Session) -> list[dict]:
    r = s.get("https://huanaihub.com/client/orders", timeout=60)
    r.raise_for_status()
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(cells) < 4:
            continue
        plain = [re.sub(r"<[^>]+>", " ", c) for c in cells]
        plain = [re.sub(r"\s+", " ", c).strip() for c in plain]
        onclick = re.search(
            r"downloadFile\s*\(\s*[`'\"]([A-Z0-9]+)[`'\"]",
            tr,
            re.I,
        )
        trans_id = onclick.group(1) if onclick else ""
        if not trans_id:
            m = re.search(r"/client/order/([A-Z0-9]+)", tr, re.I)
            trans_id = m.group(1) if m else ""
        if not trans_id:
            continue
        rows.append(
            {
                "trans_id": trans_id,
                "product": plain[1] if len(plain) > 1 else "",
                "amount": plain[2] if len(plain) > 2 else "",
                "price": plain[3] if len(plain) > 3 else "",
                "date": plain[4] if len(plain) > 4 else "",
                "row": " | ".join(plain),
            }
        )
    return rows


def download_order(s: requests.Session, trans_id: str, token: str) -> str:
    r = s.post(
        "https://huanaihub.com/ajaxs/client/downloadOrder.php",
        data={"transid": trans_id, "token": token},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Download {trans_id} fail: {data.get('msg') or data}")
    accounts = (data.get("accounts") or "").replace("\r\n", "\n").strip()
    if not accounts:
        raise RuntimeError(f"Download {trans_id} — accounts rỗng")
    return accounts


def build_pool(
    lines: list[str],
    *,
    trans_id: str,
    credits: int,
    source: str = "huanaihub",
) -> dict:
    now = int(time.time())
    accounts = []
    seen: set[str] = set()
    for raw in lines:
        email, password = parse_roboneo_account(raw)
        key = email.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        accounts.append(
            {
                "email": email.strip(),
                "password": password,
                "status": "active",
                "source": source,
                "trans_id": trans_id,
                "credits": int(credits),
                "updated_at": now,
                "last_sync_at": now,
                "reserved": 0,
                "note": f"gói {credits} carrot — import mới",
            }
        )
    return {
        "accounts": accounts,
        "last_proxy_rotate_at": 0,
        "accounts_on_current_ip": 0,
        "pool_note": f"motionaistudio batch {trans_id} ({len(accounts)} nick)",
    }


def backup_pool(pool_path: Path, backup_dir: Path) -> Path | None:
    if not pool_path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"account_pool_{ts}_{pool_path.name}"
    shutil.copy2(pool_path, dest)
    return dest


def main() -> int:
    p = argparse.ArgumentParser(description="Tải đơn huanaihub → pool RoboNeo active 120")
    p.add_argument("--trans-id", help="Mã đơn. Bỏ trống = đơn mới nhất hoặc --amount")
    p.add_argument("--amount", type=int, default=94, help="Lọc đơn theo số nick (mặc định 94)")
    p.add_argument("--credits", type=int, default=120, help="Credit ghi vào pool (mặc định 120)")
    p.add_argument(
        "--pool",
        default="",
        help="Đường dẫn pool output (mặc định ROBONEO_POOL_FILE hoặc account_pool.json)",
    )
    p.add_argument("--backup-dir", default="", help="Thư mục backup pool cũ")
    p.add_argument("--dry-run", action="store_true", help="Chỉ tải nick, không ghi pool")
    p.add_argument("--list", action="store_true", help="Liệt kê đơn")
    p.add_argument("-o", "--output-txt", default="", help="Lưu nick thô ra file text")
    args = p.parse_args()

    load_project_env()
    s = _session()
    login(s)
    token = _client_token(s)
    orders = list_orders(s)
    if not orders:
        print("❌ Không parse được đơn từ /client/orders")
        return 1

    print(f"📋 {len(orders)} đơn gần nhất:")
    for o in orders[:20]:
        print(
            f"  {o['trans_id']} | {o.get('amount', '?')} nick | "
            f"{o.get('product', '')[:45]} | {o.get('date', '')}"
        )

    if args.list:
        return 0

    chosen = None
    if args.trans_id:
        tid = args.trans_id.strip().upper()
        for o in orders:
            if o["trans_id"].upper() == tid:
                chosen = o
                break
        if not chosen:
            chosen = {"trans_id": tid}
    elif args.amount:
        for o in orders:
            amt = re.sub(r"\D", "", o.get("amount") or "")
            if amt == str(args.amount):
                chosen = o
                break
    if not chosen:
        chosen = orders[0]

    trans_id = chosen["trans_id"]
    print(f"⬇️  Tải đơn {trans_id} ...")
    accounts_text = download_order(s, trans_id, token)
    lines = [ln.strip() for ln in accounts_text.splitlines() if ln.strip()]
    print(f"✅ Tải được {len(lines)} nick")

    if args.output_txt:
        Path(args.output_txt).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"   → {args.output_txt}")

    pool_data = build_pool(lines, trans_id=trans_id, credits=args.credits)
    print(
        f"📦 Pool mới: {len(pool_data['accounts'])} nick | "
        f"active | credits={args.credits}"
    )

    if args.dry_run:
        return 0

    pool_path = Path(args.pool) if args.pool else ROOT / "account_pool.json"
    env_pool = (get_env("ROBONEO_POOL_FILE") or "").strip()
    if not args.pool and env_pool:
        pool_path = Path(env_pool)

    backup_dir = Path(args.backup_dir) if args.backup_dir else pool_path.parent / "backups"
    backed = backup_pool(pool_path, backup_dir)
    if backed:
        print(f"💾 Backup pool cũ → {backed}")
    else:
        print(f"ℹ️  Không có pool cũ tại {pool_path}")

    pool_path.parent.mkdir(parents=True, exist_ok=True)
    pool_path.write_text(json.dumps(pool_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✅ Ghi pool mới → {pool_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
