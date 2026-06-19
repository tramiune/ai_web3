"""
Pool nick RoboNeo — ước tính credit theo giây, chọn / mua nick phù hợp.

Quy ước user: 15 giây video ≈ 115 credit → ~7.67 credit/giây.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from project_env import get_env, load_project_env
from huanaihub import HuanAiHubError, buy_roboneo_account, default_product_id
from roboneo_proxy import probe_proxy, proxy_dict_from_key, roboneo_login
from roboneo_web import RoboNeoWebClient, RoboNeoError

POOL_FILE = Path(__file__).resolve().parent / "account_pool.json"


def _pool_path() -> Path:
    load_project_env()
    raw = (get_env("ROBONEO_POOL_FILE") or "").strip()
    if raw:
        return Path(raw)
    return POOL_FILE


def credits_per_15s() -> float:
    load_project_env()
    return float(get_env("ROBONEO_CREDITS_PER_15S", "115") or "115")


def proxy_rotate_cooldown_sec() -> int:
    load_project_env()
    return int(get_env("PROXY_ROTATE_COOLDOWN_SEC", "60") or "60")


def max_accounts_per_ip() -> int:
    """Số nick mua/login mới trên cùng 1 IP VNsProxy trước khi bắt buộc xoay."""
    load_project_env()
    return max(1, int(get_env("PROXY_ACCOUNTS_PER_IP", "2") or "2"))


def _ensure_pool_defaults(data: dict[str, Any]) -> None:
    if "accounts_on_current_ip" not in data:
        active = [a for a in data.get("accounts") or [] if a.get("status") == "active"]
        data["accounts_on_current_ip"] = min(len(active), max_accounts_per_ip())


def _should_rotate_for_new_buy(data: dict[str, Any]) -> bool:
    _ensure_pool_defaults(data)
    return int(data.get("accounts_on_current_ip") or 0) >= max_accounts_per_ip()


def _should_force_rotate_on_error(err: object) -> bool:
    s = str(err or "").lower()
    return any(
        x in s
        for x in (
            "10114",
            "captcha",
            "verification",
            "429",
            "proxy",
            "45130",
            "login fail",
            "403",
            "connection",
            "timeout",
            "huanai",
            "out of stock",
            "sold out",
            "hết hàng",
            "không mua",
            "too many",
        )
    )


def _rotate_proxy_if_needed(data: dict[str, Any], *, force: bool) -> bool:
    """Xoay IP VNsProxy nếu cần. Trả True nếu đã xoay. Luôn chờ cooldown ≥60s trước khi xoay."""
    _ensure_pool_defaults(data)
    if not force and not _should_rotate_for_new_buy(data):
        used = int(data.get("accounts_on_current_ip") or 0)
        limit = max_accounts_per_ip()
        if used > 0:
            print(f"→ Dùng IP hiện tại ({used}/{limit} nick trên IP)")
        return False

    load_project_env()
    key = (get_env("ROBONEO_PROXY_KEY") or "").strip()
    if not key:
        return False

    _wait_proxy_rotate_cooldown(data)
    province_raw = (get_env("ROBONEO_PROXY_PROVINCE_ID") or "").strip()
    province_id = int(province_raw) if province_raw else None

    from roboneo_proxy import proxy_dict_rotate_with_fallback

    proxies, host, rotated = proxy_dict_rotate_with_fallback(key, province_id=province_id)
    if not probe_proxy(proxies):
        raise RoboNeoError(f"IP mới {host} không kết nối được sau xoay")

    data = _load_pool()
    data["last_proxy_rotate_at"] = int(time.time())
    data["accounts_on_current_ip"] = 0
    _save_pool(data)
    print(f"🔄 Xoay IP → {host} (cooldown {proxy_rotate_cooldown_sec()}s, tối đa {max_accounts_per_ip()} nick/IP)")
    return True


def estimate_credits(duration_sec: float, *, buffer_pct: float = 0.05) -> int:
    """Credit dự kiến cho 1 job motion theo độ dài video mẫu (giây)."""
    if duration_sec <= 0:
        duration_sec = 5.0
    raw = duration_sec * credits_per_15s() / 15.0
    need = math.ceil(raw * (1.0 + buffer_pct))
    return max(need, 1)


def min_reuse_credits() -> int:
    """Credit tối thiểu để giữ nick active sau 1 job."""
    load_project_env()
    sec = float(get_env("ROBONEO_MIN_REUSE_VIDEO_SEC", "5") or "5")
    return estimate_credits(sec, buffer_pct=0.0)


def video_duration_sec(path: str | Path) -> float:
    path = Path(path)
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(out.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return float(get_env("ROBONEO_DEFAULT_VIDEO_SEC", "5") or "5")


def _load_pool() -> dict[str, Any]:
    path = _pool_path()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"accounts": [], "last_proxy_rotate_at": 0, "accounts_on_current_ip": 0}


def _save_pool(data: dict[str, Any]) -> None:
    path = _pool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_accounts() -> list[dict[str, Any]]:
    return list(_load_pool().get("accounts") or [])


def upsert_account(
    email: str,
    password: str,
    *,
    credits: int | None = None,
    status: str = "active",
    source: str = "manual",
    trans_id: str = "",
    uid: int | None = None,
) -> dict[str, Any]:
    data = _load_pool()
    accounts: list[dict[str, Any]] = data.setdefault("accounts", [])
    email = email.strip().lower()
    row = next((a for a in accounts if a.get("email", "").lower() == email), None)
    if row is None:
        row = {"email": email, "password": password, "status": status, "source": source}
        accounts.append(row)
    row["password"] = password
    row["status"] = status
    row["source"] = source or row.get("source", "manual")
    if trans_id:
        row["trans_id"] = trans_id
    if uid is not None:
        row["uid"] = uid
    if credits is not None:
        row["credits"] = int(credits)
    row["updated_at"] = int(time.time())
    _save_pool(data)
    return row


def mark_account(
    email: str,
    *,
    status: str,
    note: str = "",
    credits: int | None = None,
) -> None:
    data = _load_pool()
    for row in data.get("accounts") or []:
        if row.get("email", "").lower() == email.strip().lower():
            row["status"] = status
            if note:
                row["note"] = note
            if credits is not None:
                row["credits"] = int(credits)
            row["updated_at"] = int(time.time())
            break
    _save_pool(data)


def pick_account(
    credits_needed: int,
    *,
    prefer_higher: bool = False,
    exclude: set[str] | None = None,
) -> dict[str, Any] | None:
    """Chọn nick active đủ credit. Mặc định: nick nhỏ nhất vẫn đủ (tiết kiệm nick lớn)."""
    rows = list_eligible_accounts(credits_needed, exclude=exclude)
    if not rows:
        return None
    if prefer_higher:
        return max(rows, key=lambda a: int(a.get("credits") or 0))
    return min(rows, key=lambda a: int(a.get("credits") or 0))


def list_eligible_accounts(
    credits_needed: int,
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    skip = {e.strip().lower() for e in (exclude or set()) if e}
    out: list[dict[str, Any]] = []
    for a in list_accounts():
        email = (a.get("email") or "").strip().lower()
        if not email or email in skip:
            continue
        st = a.get("status")
        if st == "locked":
            continue
        if st not in ("active", "depleted"):
            continue
        c = a.get("credits")
        if c is None:
            out.append(a)
        elif int(c) >= credits_needed:
            out.append(a)
        elif st == "depleted":
            # depleted trong JSON có thể sai — login lại kiểm credit thật
            out.append(a)
    return out


def _account_pick_sort_key(a: dict[str, Any]) -> tuple:
    st_rank = 0 if a.get("status") == "active" else 1
    c = a.get("credits")
    if c is None:
        return (st_rank, 1, 999999)
    return (st_rank, 0, int(c))


def update_account_after_job(email: str, remaining: int) -> None:
    """Cập nhật pool sau job — giữ active nếu còn đủ credit cho job tiếp."""
    floor = min_reuse_credits()
    if remaining >= floor:
        mark_account(email, status="active", credits=remaining, note="")
    else:
        mark_account(
            email,
            status="depleted",
            credits=remaining,
            note=f"còn {remaining} credit (< {floor})",
        )


def _wait_proxy_rotate_cooldown(data: dict[str, Any]) -> None:
    cooldown = proxy_rotate_cooldown_sec()
    last = float(data.get("last_proxy_rotate_at") or 0)
    wait = cooldown - (time.time() - last)
    if wait > 0:
        print(f"⏱ Đợi {wait:.0f}s (VNsProxy 1 lần/60s)…")
        time.sleep(wait)


def _roboneo_account_id(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def _login_once(email: str, password: str, *, rotate: bool = False) -> tuple[RoboNeoWebClient, dict[str, Any]]:
    load_project_env()
    account_id = _roboneo_account_id(email)
    key = (get_env("ROBONEO_PROXY_KEY") or "").strip() or None
    province_raw = (get_env("ROBONEO_PROXY_PROVINCE_ID") or "").strip()
    province_id = int(province_raw) if province_raw else None

    proxies = None
    host = ""
    if key:
        if rotate:
            data = _load_pool()
            _wait_proxy_rotate_cooldown(data)
            from roboneo_proxy import proxy_dict_rotate_with_fallback

            proxies, host, _ = proxy_dict_rotate_with_fallback(key, province_id=province_id)
            data = _load_pool()
            data["last_proxy_rotate_at"] = int(time.time())
            data["accounts_on_current_ip"] = 0
            _save_pool(data)
        else:
            proxies, host = proxy_dict_from_key(key, rotate=False, province_id=province_id)

    resp = roboneo_login(email, password, proxies=proxies)
    client = RoboNeoWebClient(account_id=account_id)
    if host:
        client._apply_proxies(host)
    uid = resp.get("uid")
    client._state.update(
        {
            "access_token": resp["access_token"],
            "refresh_token": resp.get("refresh_token", ""),
            "uid": uid,
            "gid": client._gid,
            "proxy": host or None,
        }
    )
    client._save_session()
    try:
        client.fetch_token_info()
    except Exception:
        pass
    bal = client.meiye_query()
    credits = int(bal.get("amount") or 0) if isinstance(bal, dict) else 0
    upsert_account(email, password, credits=credits, status="active", uid=int(uid) if uid else None)
    return client, {"email": email, "uid": uid, "credits": credits, "proxy": host}


def refresh_account_credits(client: RoboNeoWebClient, email: str) -> int:
    bal = client.meiye_query()
    credits = int(bal.get("amount") or 0) if isinstance(bal, dict) else 0
    row = next((a for a in list_accounts() if a.get("email") == email), None)
    if row:
        upsert_account(email, row["password"], credits=credits, status=row.get("status", "active"))
    return credits


def buy_and_register_account(*, force_rotate: bool = False) -> tuple[RoboNeoWebClient, dict[str, Any]]:
    data = _load_pool()
    _rotate_proxy_if_needed(data, force=force_rotate)

    account = buy_roboneo_account(product_id=default_product_id(), amount=1)
    print(f"✅ Mua nick {account.email} (trans {account.trans_id})")
    try:
        client, info = _login_once(account.email, account.password, rotate=False)
        info["password"] = account.password
        upsert_account(
            account.email,
            account.password,
            credits=info["credits"],
            status="active",
            source="huanaihub",
            trans_id=account.trans_id,
            uid=info.get("uid"),
        )
        data = _load_pool()
        data["accounts_on_current_ip"] = int(data.get("accounts_on_current_ip") or 0) + 1
        _save_pool(data)
        return client, info
    except Exception as e:
        upsert_account(
            account.email,
            account.password,
            status="locked",
            source="huanaihub",
            trans_id=account.trans_id,
            credits=0,
        )
        mark_account(account.email, status="locked", note=str(e))
        raise


def acquire_client_for_job(
    credits_needed: int,
    *,
    max_buy_attempts: int = 3,
    exclude_emails: set[str] | None = None,
) -> tuple[RoboNeoWebClient, dict[str, Any]]:
    """
    Chọn nick pool đủ credit; không có thì mua nick mới.
    VNsProxy: tối đa PROXY_ACCOUNTS_PER_IP (mặc định 2) nick/IP, chỉ xoay khi hết slot hoặc lỗi;
    chờ PROXY_ROTATE_COOLDOWN_SEC (60s) trước mỗi lần xoay.
    """
    excluded = {e.strip().lower() for e in (exclude_emails or set()) if e}
    print(f"→ Cần ~{credits_needed} credit (quy đổi {credits_per_15s()}/15s)")

    for row in sorted(
        list_eligible_accounts(credits_needed, exclude=excluded),
        key=_account_pick_sort_key,
    ):
        cr_label = row.get("credits")
        print(f"→ Dùng nick pool {row['email']} ({cr_label if cr_label is not None else '?'} credit)")
        try:
            client, info = _login_once(row["email"], row["password"], rotate=False)
            if info["credits"] < credits_needed:
                print(
                    f"⚠ Credit thực {info['credits']} < cần {credits_needed} — đổi nick…"
                )
                mark_account(row["email"], status="depleted", note="credit không đủ sau login")
                excluded.add(row["email"].strip().lower())
                continue
            return client, info
        except Exception as e:
            print(f"⚠ Nick pool fail: {e}")
            mark_account(row["email"], status="locked", note=str(e))
            excluded.add(row["email"].strip().lower())

    last_err: Exception | None = None
    force_rotate = False
    for attempt in range(1, max_buy_attempts + 1):
        print(f"→ Mua nick mới (lần {attempt}/{max_buy_attempts})…")
        try:
            client, info = buy_and_register_account(force_rotate=force_rotate)
            email_l = (info.get("email") or "").strip().lower()
            if email_l in excluded:
                mark_account(info["email"], status="depleted", note="đã thử trước đó")
                continue
            if info["credits"] >= credits_needed:
                return client, info
            print(
                f"⚠ Nick mới {info['email']} chỉ {info['credits']} credit "
                f"< {credits_needed} — mua nick khác…"
            )
            mark_account(info["email"], status="depleted", note="credit thấp sau mua")
            excluded.add(email_l)
            force_rotate = False
        except (HuanAiHubError, Exception) as e:
            last_err = e
            print(f"   ⚠ {e}")
            if _should_force_rotate_on_error(e):
                print("   → Lần sau sẽ xoay IP (chờ cooldown VNsProxy nếu cần)…")
                force_rotate = True
    if last_err:
        raise RoboNeoError(f"Không có nick đủ {credits_needed} credit: {last_err}")
    raise RoboNeoError(f"Không có nick đủ {credits_needed} credit")
