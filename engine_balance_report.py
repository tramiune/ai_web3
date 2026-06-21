"""Thu thập số dư nick VAE / XiaoYang / Aidancing từ .env + API."""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from project_env import get_env, load_project_env
from videoaieasy_web import VideoAiEasyClient, profile_credits
from xiaoyang_web import XiaoyangWebClient, XiaoyangAuthError


def _account_id(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def _load_xy_api_keys() -> list[str]:
    raw = (get_env("XIAOYANG_API_KEYS") or "").strip()
    single = (get_env("XIAOYANG_API_KEY") or "").strip()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if keys:
        return keys
    return [single] if single else []


def collect_engine_balances() -> dict[str, Any]:
    load_project_env()
    from xiaoyang_motion import load_videoaieasy_accounts, load_xiaoyang_accounts

    vae_rows: list[dict[str, Any]] = []
    for acc in load_videoaieasy_accounts():
        email = acc.get("email") or "?"
        password = acc.get("password") or ""
        aid = acc.get("id") or _account_id(email)
        row: dict[str, Any] = {"email": email, "coins": None, "xu": None, "error": ""}
        try:
            client = VideoAiEasyClient(account_id=aid)
            profile = client.ensure_session(email, password)
            coins = profile_credits(profile)
            row["coins"] = int(coins)
            row["xu"] = round(coins / 10.0, 2)
        except Exception as e:
            row["error"] = str(e)[:300]
        vae_rows.append(row)

    xy_rows: list[dict[str, Any]] = []
    for acc in load_xiaoyang_accounts():
        email = acc.get("email") or "?"
        password = acc.get("password") or ""
        aid = acc.get("id") or _account_id(email)
        row = {"email": email, "credits": None, "error": ""}
        try:
            client = XiaoyangWebClient(account_id=aid)
            try:
                me = client.me()
            except XiaoyangAuthError:
                client.login(email=email, password=password)
                me = client.me()
            row["credits"] = int(me.get("credits") or me.get("credit") or 0)
        except Exception as e:
            row["error"] = str(e)[:300]
        xy_rows.append(row)

    xy_api_rows: list[dict[str, Any]] = []
    try:
        from xiaoyang_api import XiaoyangApiClient

        for i, key in enumerate(_load_xy_api_keys(), 1):
            masked = f"key#{i} …{key[-6:]}" if len(key) > 6 else f"key#{i}"
            row = {"email": masked, "credits": None, "error": ""}
            try:
                me = XiaoyangApiClient(api_key=key).me()
                row["email"] = (me.get("email") or masked).strip()
                row["credits"] = int(me.get("credits") or 0)
            except Exception as e:
                row["error"] = str(e)[:300]
            xy_api_rows.append(row)
    except ImportError:
        pass

    aid_row: dict[str, Any] = {"coins": None, "error": ""}
    cookie = (get_env("AIDANCING_COOKIE") or "").strip()
    if not cookie:
        aid_row["error"] = "Thiếu AIDANCING_COOKIE"
    else:
        try:
            from aidancing_api import AidancingApiClient, SessionExpiredError

            aid_row["coins"] = AidancingApiClient(cookie=cookie).get_balance()
        except SessionExpiredError as e:
            aid_row["error"] = str(e)[:300]
        except Exception as e:
            aid_row["error"] = str(e)[:300]

    def _sum_int(rows: list[dict], key: str) -> int:
        return sum(int(r[key]) for r in rows if r.get(key) is not None and not r.get("error"))

    return {
        "vae": vae_rows,
        "xiaoyangWeb": xy_rows,
        "xiaoyangApi": xy_api_rows,
        "aidancing": aid_row,
        "totals": {
            "vaeCoins": _sum_int(vae_rows, "coins"),
            "vaeXu": round(_sum_int(vae_rows, "coins") / 10.0, 2),
            "xiaoyangWebCredits": _sum_int(xy_rows, "credits"),
            "xiaoyangApiCredits": _sum_int(xy_api_rows, "credits"),
            "aidancingCoins": aid_row.get("coins"),
        },
    }


def format_engine_balance_report(site: str, data: dict[str, Any]) -> str:
    lines = [f"{'=' * 56}", f"  {site.upper()} — số dư engine nick", f"{'=' * 56}"]

    lines.append("\n▸ VAE (VideoAiEasy) — coins (10 coins = 1 xu)")
    vae = data.get("vae") or []
    if not vae:
        lines.append("  (không cấu hình VIDEOAIEASY_ACCOUNTS)")
    for r in vae:
        if r.get("error"):
            lines.append(f"  • {r['email']}: ERR — {r['error'][:120]}")
        else:
            lines.append(f"  • {r['email']}: {r['coins']} coins ({r['xu']} xu)")
    if vae:
        t = data.get("totals") or {}
        lines.append(f"  → Tổng: {t.get('vaeCoins', 0)} coins ({t.get('vaeXu', 0)} xu)")

    lines.append("\n▸ XiaoYang (web nick) — credits")
    xy = data.get("xiaoyangWeb") or []
    if not xy:
        lines.append("  (không cấu hình XIAOYANG_ACCOUNTS)")
    for r in xy:
        if r.get("error"):
            lines.append(f"  • {r['email']}: ERR — {r['error'][:120]}")
        else:
            lines.append(f"  • {r['email']}: {r['credits']} credits")
    if xy:
        lines.append(f"  → Tổng: {(data.get('totals') or {}).get('xiaoyangWebCredits', 0)} credits")

    xy_api = data.get("xiaoyangApi") or []
    if xy_api:
        lines.append("\n▸ XiaoYang (API key) — credits")
        for r in xy_api:
            if r.get("error"):
                lines.append(f"  • {r['email']}: ERR — {r['error'][:120]}")
            else:
                lines.append(f"  • {r['email']}: {r['credits']} credits")
        lines.append(f"  → Tổng: {(data.get('totals') or {}).get('xiaoyangApiCredits', 0)} credits")

    lines.append("\n▸ Aidancing — coin")
    ad = data.get("aidancing") or {}
    if ad.get("error"):
        lines.append(f"  • {ad['error']}")
    else:
        lines.append(f"  • {ad.get('coins')} coin")
    lines.append("")
    return "\n".join(lines)


def sync_engine_balances_to_firestore(db, bot_name: str) -> dict[str, Any]:
    """Ghi engineBalances lên Firestore bots/{bot_name} — admin đọc được."""
    from firebase_admin import firestore

    data = collect_engine_balances()
    db.collection("bots").document(bot_name).set(
        {
            "engineBalances": data,
            "engineBalancesUpdatedAt": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return data
