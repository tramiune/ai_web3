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
from collections.abc import Callable
from typing import Any

from project_env import get_env, load_project_env
from huanaihub import HuanAiHubError, buy_roboneo_account, default_product_id
from roboneo_proxy import probe_proxy, proxy_dict_from_key, roboneo_login
from roboneo_web import RoboNeoAuthError, RoboNeoWebClient, RoboNeoError, resolve_surface

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
    """Số nick login tối đa trên cùng 1 IP VNsProxy — luôn xoay IP trước nick thứ (limit+1)."""
    load_project_env()
    return max(1, int(get_env("PROXY_ACCOUNTS_PER_IP", "2") or "2"))


def auto_buy_enabled() -> bool:
    """False khi ROBONEO_AUTO_BUY=0 — chỉ dùng nick có sẵn trong pool, không gọi huanaihub."""
    load_project_env()
    raw = (get_env("ROBONEO_AUTO_BUY", "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _ensure_pool_defaults(data: dict[str, Any]) -> None:
    if "current_ip_emails" not in data:
        old_used = int(data.get("accounts_on_current_ip") or 0)
        limit = max_accounts_per_ip()
        if old_used >= limit:
            # Pool cũ không lưu danh sách nick/IP — coi IP hiện tại đã đầy, login nick mới sẽ xoay IP.
            data["current_ip_emails"] = [f"__ip_full_{i}__" for i in range(limit)]
        else:
            data["current_ip_emails"] = []
    if "accounts_on_current_ip" not in data:
        data["accounts_on_current_ip"] = len(data["current_ip_emails"])
    else:
        data["accounts_on_current_ip"] = len(_current_ip_emails(data))


def _current_ip_emails(data: dict[str, Any]) -> list[str]:
    return [
        str(e).strip().lower()
        for e in (data.get("current_ip_emails") or [])
        if str(e).strip()
    ]


def _clear_current_ip_usage(data: dict[str, Any]) -> None:
    data["current_ip_emails"] = []
    data["accounts_on_current_ip"] = 0


def _must_rotate_before_login(data: dict[str, Any], email: str, *, rotate: bool) -> bool:
    _ensure_pool_defaults(data)
    if rotate:
        return True
    email_l = email.strip().lower()
    emails = _current_ip_emails(data)
    if email_l in emails:
        return False
    return len(emails) >= max_accounts_per_ip()


def _record_login_on_current_ip(email: str) -> None:
    data = _load_pool()
    _ensure_pool_defaults(data)
    email_l = email.strip().lower()
    emails = _current_ip_emails(data)
    if email_l not in emails:
        emails.append(email_l)
    data["current_ip_emails"] = emails
    data["accounts_on_current_ip"] = len(emails)
    _save_pool(data)
    print(f"   IP hiện tại: {len(emails)}/{max_accounts_per_ip()} nick")


def _should_rotate_for_new_buy(data: dict[str, Any]) -> bool:
    _ensure_pool_defaults(data)
    return len(_current_ip_emails(data)) >= max_accounts_per_ip()


def _should_force_rotate_on_error(err: object) -> bool:
    s = str(err or "").lower()
    return any(
        x in s
        for x in (
            "10114",
            "captcha",
            "verification",
            "429",
            "400",
            "bad request",
            "vnsproxy",
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


def rotate_proxy_for_retry() -> bool:
    """Xoay IP VNsProxy trước mỗi lần retry RoboNeo (respect cooldown 60s)."""
    data = _load_pool()
    try:
        return _rotate_proxy_if_needed(data, force=True)
    except Exception as e:
        print(f"⚠️ Xoay IP retry: {e}")
        return False


def _rotate_proxy_if_needed(data: dict[str, Any], *, force: bool) -> bool:
    """Xoay IP VNsProxy nếu cần. Trả True nếu đã xoay. Luôn chờ cooldown ≥60s trước khi xoay."""
    _ensure_pool_defaults(data)
    if not force and not _should_rotate_for_new_buy(data):
        used = len(_current_ip_emails(data))
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
    _clear_current_ip_usage(data)
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


def min_pick_credits() -> int:
    """Sàn credit khi chọn nick pool — chỉ dùng nick ghi ≥120 coin trong pool."""
    load_project_env()
    return max(1, int(get_env("ROBONEO_MIN_PICK_CREDITS", "120") or "120"))


def pick_credits_for_job(duration_sec: float) -> tuple[int, int]:
    """(ước tính theo video, ngưỡng chọn nick) — pick = max(estimate, min_pick)."""
    est = estimate_credits(duration_sec)
    return est, max(est, min_pick_credits())


def required_credits_from_cost(*, estimate: int, cost_item: dict[str, Any] | None) -> int:
    """
    Credit thực cần sau count_cost.
    Chỉ dùng fallback_cost / real_cost — field cost (115) là hằng rate, không phải giá job.
    """
    required = max(estimate, min_pick_credits())
    if not cost_item:
        return required
    for key in ("fallback_cost", "real_cost"):
        val = cost_item.get(key)
        if val is None:
            continue
        try:
            required = max(required, math.ceil(float(val)))
        except (TypeError, ValueError):
            pass
    return required


def credit_sync_ttl_sec() -> int:
    load_project_env()
    return max(30, int(get_env("ROBONEO_CREDIT_SYNC_TTL_SEC", "180") or "180"))


def effective_credits(row: dict[str, Any]) -> int | None:
    """Credit khả dụng sau khi trừ phần đang giữ cho đơn chưa xong."""
    raw = row.get("credits")
    if raw is None:
        return None
    reserved = int(row.get("reserved") or 0)
    return max(0, int(raw) - reserved)


def _patch_account_row(email: str, **fields: Any) -> None:
    email_l = email.strip().lower()
    data = _load_pool()
    for row in data.get("accounts") or []:
        if (row.get("email") or "").strip().lower() == email_l:
            row.update(fields)
            row["updated_at"] = int(time.time())
            _save_pool(data)
            return


def reserve_credits(email: str, amount: int) -> None:
    if amount <= 0:
        return
    email_l = email.strip().lower()
    data = _load_pool()
    for row in data.get("accounts") or []:
        if (row.get("email") or "").strip().lower() == email_l:
            row["reserved"] = max(0, int(row.get("reserved") or 0)) + int(amount)
            row["updated_at"] = int(time.time())
            _save_pool(data)
            return


def release_reserved(email: str, amount: int) -> None:
    if amount <= 0:
        return
    email_l = email.strip().lower()
    data = _load_pool()
    for row in data.get("accounts") or []:
        if (row.get("email") or "").strip().lower() == email_l:
            cur = max(0, int(row.get("reserved") or 0))
            row["reserved"] = max(0, cur - int(amount))
            row["updated_at"] = int(time.time())
            _save_pool(data)
            return


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
        return max(rows, key=lambda a: effective_credits(a) or 0)
    return min(rows, key=lambda a: effective_credits(a) if effective_credits(a) is not None else 999999)


def list_eligible_accounts(
    credits_needed: int,
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    skip = {e.strip().lower() for e in (exclude or set()) if e}
    floor = max(credits_needed, min_pick_credits())
    out: list[dict[str, Any]] = []
    for a in list_accounts():
        email = (a.get("email") or "").strip().lower()
        if not email or email in skip:
            continue
        if a.get("status") != "active":
            continue
        eff = effective_credits(a)
        if eff is not None and eff >= floor:
            out.append(a)
    return out


def _account_pick_sort_key(a: dict[str, Any]) -> tuple:
    eff = effective_credits(a) or 0
    return (0, eff)


def update_account_after_job(email: str, remaining: int) -> None:
    """Cập nhật pool sau job — chỉ giữ active nếu còn ≥120 credit (đủ chọn lại)."""
    floor = min_pick_credits()
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
        data = _load_pool()
        _ensure_pool_defaults(data)
        used = len(_current_ip_emails(data))
        limit = max_accounts_per_ip()
        must_rotate = _must_rotate_before_login(data, email, rotate=rotate)
        if must_rotate:
            if not rotate and used >= limit:
                print(f"→ Đã {used}/{limit} nick trên IP — xoay IP trước login {email}…")
            _wait_proxy_rotate_cooldown(data)
            from roboneo_proxy import proxy_dict_rotate_with_fallback

            proxies, host, _ = proxy_dict_rotate_with_fallback(key, province_id=province_id)
            data = _load_pool()
            data["last_proxy_rotate_at"] = int(time.time())
            _clear_current_ip_usage(data)
            _save_pool(data)
        else:
            proxies, host = proxy_dict_from_key(key, rotate=False, province_id=province_id)
            if used > 0:
                print(f"→ Login trên IP hiện tại ({used}/{limit} nick đã login)")

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
    _patch_account_row(email, last_sync_at=int(time.time()), reserved=0)
    if key:
        _record_login_on_current_ip(email)
    return client, {"email": email, "uid": uid, "credits": credits, "proxy": host}


def get_or_refresh_client(
    email: str,
    password: str,
    *,
    force_sync: bool = False,
    surface: str | None = None,
) -> tuple[RoboNeoWebClient, dict[str, Any]]:
    """Dùng session file nếu còn; chỉ login khi hết token. Sync credit qua meiye_query."""
    load_project_env()
    email = email.strip().lower()
    account_id = _roboneo_account_id(email)
    client = RoboNeoWebClient(account_id=account_id)
    surf = surface or resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))

    row = next((a for a in list_accounts() if (a.get("email") or "").lower() == email), None)
    stale = True
    if row and row.get("last_sync_at"):
        stale = (time.time() - int(row["last_sync_at"])) > credit_sync_ttl_sec()

    # Chỉ dùng session file đã load — không gọi ensure_session/login trực tiếp (tránh bỏ qua giới hạn nick/IP).
    need_login = not (client._state.get("access_token") or "").strip()
    if need_login:
        return _login_once(email, password, rotate=False)

    if force_sync or stale or row is None or row.get("credits") is None:
        try:
            bal = client.meiye_query(surface=surf)
            credits = int(bal.get("amount") or 0) if isinstance(bal, dict) else 0
            pwd = (row or {}).get("password") or password
            upsert_account(email, pwd, credits=credits, status=(row or {}).get("status", "active"))
            _patch_account_row(email, last_sync_at=int(time.time()))
        except RoboNeoAuthError:
            return _login_once(email, password, rotate=False)
    else:
        credits = int(row.get("credits") or 0)

    return client, {
        "email": email,
        "uid": client.uid,
        "credits": credits,
        "proxy": client._state.get("proxy"),
    }


def refresh_account_credits(
    client: RoboNeoWebClient,
    email: str,
    *,
    surface: str | None = None,
    release_reserved_amount: int = 0,
) -> int:
    load_project_env()
    surf = surface or resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))
    bal = client.meiye_query(surface=surf)
    credits = int(bal.get("amount") or 0) if isinstance(bal, dict) else 0
    row = next((a for a in list_accounts() if (a.get("email") or "").lower() == email.strip().lower()), None)
    if row:
        upsert_account(email, row["password"], credits=credits, status=row.get("status", "active"))
        _patch_account_row(email, last_sync_at=int(time.time()))
    if release_reserved_amount > 0:
        release_reserved(email, release_reserved_amount)
    return credits


def sync_stale_pool_credits(
    *,
    surface: str | None = None,
    max_accounts: int | None = None,
) -> int:
    """Sync credit các nick stale/unknown — session trước, login chỉ khi cần."""
    load_project_env()
    surf = surface or resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))
    limit = max_accounts
    if limit is None:
        limit = max(0, int(get_env("ROBONEO_STARTUP_SYNC_MAX", "15") or "15"))
    synced = 0
    for row in list_accounts():
        if limit and synced >= limit:
            break
        if row.get("status") == "locked":
            continue
        stale = not row.get("last_sync_at") or (
            time.time() - int(row["last_sync_at"])
        ) > credit_sync_ttl_sec()
        if not stale and row.get("credits") is not None:
            continue
        email = (row.get("email") or "").strip()
        password = row.get("password") or ""
        if not email or not password:
            continue
        try:
            get_or_refresh_client(email, password, force_sync=True, surface=surf)
            synced += 1
        except Exception as e:
            print(f"  ⚠️ sync credit {email}: {e}")
    return synced


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
    slot_available: Callable[[str], bool] | None = None,
    surface: str | None = None,
) -> tuple[RoboNeoWebClient, dict[str, Any]]:
    """
    Chọn nick pool đủ credit; mua nick mới qua huanaihub chỉ khi ROBONEO_AUTO_BUY bật.
    VNsProxy: tối đa PROXY_ACCOUNTS_PER_IP (mặc định 2) nick/IP, chỉ xoay khi hết slot hoặc lỗi;
    chờ PROXY_ROTATE_COOLDOWN_SEC (60s) trước mỗi lần xoay.
    """
    excluded = {e.strip().lower() for e in (exclude_emails or set()) if e}
    floor = max(credits_needed, min_pick_credits())
    print(f"→ Cần nick pool ≥{floor} credit (job ~{credits_needed})")

    for row in sorted(
        list_eligible_accounts(credits_needed, exclude=excluded),
        key=_account_pick_sort_key,
    ):
        email = row["email"]
        if slot_available is not None and not slot_available(email):
            eff = effective_credits(row)
            print(f"→ Bỏ qua {email} (đầy slot, eff={eff if eff is not None else '?'})")
            continue
        eff = effective_credits(row)
        cr_label = eff if eff is not None else row.get("credits")
        print(f"→ Thử nick pool {email} (eff={cr_label if cr_label is not None else '?'} credit)")
        try:
            client, info = get_or_refresh_client(
                email, row["password"], surface=surface
            )
            if info["credits"] < floor:
                print(
                    f"⚠ Credit thực {info['credits']} < {floor} (pool ghi ≥{floor}) — đổi nick…"
                )
                mark_account(email, status="depleted", note="credit không đủ sau sync", credits=info["credits"])
                excluded.add(email.strip().lower())
                continue
            reserve_credits(email, credits_needed)
            info["reserved"] = credits_needed
            return client, info
        except Exception as e:
            print(f"⚠ Nick pool fail: {e}")
            mark_account(email, status="locked", note=str(e))
            excluded.add(email.strip().lower())

    if not auto_buy_enabled():
        raise RoboNeoError(
            f"Không có nick pool đủ {floor} credit "
            f"(ROBONEO_AUTO_BUY=0 — thêm nick thủ công vào pool)"
        )

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
                reserve_credits(info["email"], credits_needed)
                info["reserved"] = credits_needed
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
