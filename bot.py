"""
Kaling bot — chỉ Kling chính chủ Motion Control 2.6 / 720p (nhánh bot_kling).

  python bot.py --name kling_vps_bot
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import firebase_admin
import requests
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from project_env import get_env, load_project_env

load_project_env()

import kling_motion as kling

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

BOT_NAME = None
bot_enabled = False
bot_enabled_lock = threading.Lock()

KLING_ORIGIN = get_env("KLING_ORIGIN", "https://kling.ai").rstrip("/")
SESSION_ERROR_BACKOFF_SEC = int(get_env("SESSION_ERROR_BACKOFF_SEC", "300"))

browser_lock = threading.Lock()
submit_lock = threading.Lock()
_processing_cache: dict = {}
_processing_cache_lock = threading.Lock()
_pending_order_queue: list[str] = []
_pending_queue_lock = threading.Lock()
_pending_worker_started = False
_submitting_orders: set[str] = set()
_submitting_orders_lock = threading.Lock()
_session_error_backoff: dict[str, float] = {}

_VN_TZ = timezone(timedelta(hours=7))
_UPGRADE_MAINTENANCE_START = datetime(2026, 6, 14, 20, 30, tzinfo=_VN_TZ)
_UPGRADE_MAINTENANCE_END = datetime(2026, 6, 18, 23, 59, tzinfo=_VN_TZ)
_ADMIN_ROLES = frozenset({"admin", "super-admin"})
_SUPER_ADMIN_EMAILS = frozenset({
    "traderfinn0312@gmail.com",
    "dinhhoangvan.hh@gmail.com",
})
_admin_role_cache: dict[str, bool] = {}
_admin_role_cache_lock = threading.Lock()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8783657660:AAHRfxHNiohZzPJ2OaQ7TEMNKwb7AAlp2uo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6067707939")
_ERROR_TELEGRAM_COOLDOWN = 900
_error_telegram_sent: dict[str, float] = {}
_error_telegram_lock = threading.Lock()


def is_bot_enabled() -> bool:
    with bot_enabled_lock:
        return bot_enabled


def set_bot_enabled(value) -> None:
    global bot_enabled
    with bot_enabled_lock:
        bot_enabled = bool(value)


def _is_upgrade_maintenance_active() -> bool:
    now = datetime.now(_VN_TZ)
    return _UPGRADE_MAINTENANCE_START <= now < _UPGRADE_MAINTENANCE_END


def _is_admin_order(order_data: dict) -> bool:
    email = (order_data.get("userEmail") or "").strip().lower()
    if email in _SUPER_ADMIN_EMAILS:
        return True
    user_id = (order_data.get("userId") or "").strip()
    if not user_id:
        return False
    with _admin_role_cache_lock:
        if user_id in _admin_role_cache:
            return _admin_role_cache[user_id]
    is_admin = False
    try:
        doc = db.collection("users").document(user_id).get()
        role = (doc.to_dict() or {}).get("role") if doc.exists else None
        is_admin = role in _ADMIN_ROLES
    except Exception as exc:
        print(f"⚠️ Đọc role user {user_id}: {exc}")
    with _admin_role_cache_lock:
        _admin_role_cache[user_id] = is_admin
    return is_admin


def _should_bot_process_order(order_id: str) -> bool:
    if not _is_upgrade_maintenance_active():
        return True
    try:
        doc = db.collection("orders").document(order_id).get()
        if not doc.exists:
            return False
        if not _is_admin_order(doc.to_dict() or {}):
            print(f"⏸️ [{BOT_NAME}] Bảo trì — bỏ qua đơn {order_id}")
            return False
    except Exception as exc:
        print(f"⚠️ Kiểm tra admin đơn {order_id}: {exc}")
        return False
    return True


def _pop_processing_cache(order_id: str) -> None:
    with _processing_cache_lock:
        _processing_cache.pop(order_id, None)


def _order_already_completed(order_id: str) -> bool:
    try:
        snap = db.collection("orders").document(order_id).get()
        if not snap.exists:
            return True
        d = snap.to_dict() or {}
        return d.get("status") == "completed" or bool(d.get("resultLink"))
    except Exception as exc:
        print(f"⚠️ Không đọc đơn {order_id}: {exc}")
        return False


def _skip_if_order_done(order_id: str, reason: str) -> bool:
    if _order_already_completed(order_id):
        print(f"⏭️ Bỏ qua đơn {order_id} — {reason}")
        _pop_processing_cache(order_id)
        return True
    return False


def _pending_submit_backoff_active(order_id: str) -> bool:
    return time.time() < _session_error_backoff.get(order_id, 0)


def normalize_bot_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9_-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:64]


def ensure_bot_registered() -> None:
    ref = db.collection("bots").document(BOT_NAME)
    doc = ref.get()
    now = firestore.SERVER_TIMESTAMP
    payload = {
        "name": BOT_NAME,
        "displayName": BOT_NAME,
        "hostname": socket.gethostname(),
        "startedAt": now,
        "activeRenderProvider": kling.RENDER_PROVIDER_KLING,
    }
    if not doc.exists:
        payload.update({
            "enabled": False,
            "createdAt": now,
        })
        ref.set(payload)
        print(f"🆕 Bot mới: {BOT_NAME} (TẮT — bật trên Admin)")
    else:
        ref.set(payload, merge=True)


def on_bot_config_snapshot(keys, changes, read_time) -> None:
    if not changes:
        return
    enabled = False
    for change in changes:
        doc = change.document
        if getattr(doc, "exists", False):
            enabled = bool((doc.to_dict() or {}).get("enabled", False))
        break
    prev = is_bot_enabled()
    set_bot_enabled(enabled)
    if enabled != prev:
        status = "🟢 BẬT" if enabled else "🔴 TẮT"
        print(f"\n[{BOT_NAME}] Admin: {status}\n")


def start_bot_control_listener() -> None:
    ensure_bot_registered()
    doc = db.collection("bots").document(BOT_NAME).get()
    set_bot_enabled(bool(doc.to_dict().get("enabled", False)) if doc.exists else False)
    print(f"[{BOT_NAME}] Trạng thái: {'🟢 BẬT' if is_bot_enabled() else '🔴 TẮT'}")
    db.collection("bots").document(BOT_NAME).on_snapshot(on_bot_config_snapshot)


def send_telegram_message(text: str) -> None:
    try:
        if "[Kaling]" not in text:
            text = f"[Kaling] {text}"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        res = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if res.status_code != 200:
            print(f"❌ Telegram: {res.status_code} {res.text[:200]}")
    except Exception as exc:
        print(f"❌ Telegram: {exc}")


def notify_internal_error_telegram(order_id, order_data, err, context="") -> None:
    now = time.time()
    with _error_telegram_lock:
        if now - _error_telegram_sent.get(order_id, 0) < _ERROR_TELEGRAM_COOLDOWN:
            return
        _error_telegram_sent[order_id] = now
    short_id = order_id[-6:].upper()
    user_name = (order_data or {}).get("userName", "Khách hàng")
    user_email = (order_data or {}).get("userEmail", "N/A")
    err_text = str(err)[:500]
    ctx = f" ({context})" if context else ""
    send_telegram_message(
        f"🚨 <b>BOT KLING LỖI</b>{ctx}\n\n"
        f"🆔 #{short_id}\n👤 {user_name}\n📧 {user_email}\n"
        f"<code>{err_text}</code>"
    )


def download_file(url, filename, cookies=None, referer=None, retries=2):
    print(f"📥 Tải: {filename}...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": referer or f"{KLING_ORIGIN}/",
        "Origin": KLING_ORIGIN,
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=120)
            if response.status_code in (503, 502, 429) and attempt < retries:
                time.sleep(5 * attempt)
                continue
            response.raise_for_status()
            with open(filename, "wb") as f:
                f.write(response.content)
            return os.path.abspath(filename)
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(3 * attempt)
    print(f"❌ Tải file lỗi: {last_err}")
    return None


def upload_to_r2(file_path, folder="results"):
    from xiaoyang_direct import DirectMediaError, upload_result_file

    try:
        return upload_result_file(file_path, folder=folder)
    except DirectMediaError as exc:
        print(f"❌ R2: {exc}")
    except Exception as exc:
        print(f"❌ R2: {exc}")
    return None


def send_completion_email(order_id, order_data, result_link) -> None:
    user_email = order_data.get("userEmail")
    user_name = order_data.get("userName", "Khách hàng")
    if not user_email:
        return
    service_type = order_data.get("serviceType", "copy-motion-photo")
    service_label = {
        "copy-motion-photo": "AI Copy Chuyển Động",
        "copy-motion-multi": "AI Copy Nhảy Nhiều Người",
    }.get(service_type, service_type)
    payload = {
        "service_id": "service_6r6rd2q",
        "template_id": "template_09eir3r",
        "user_id": "92pP97oTzMGR4p_Zp",
        "template_params": {
            "user_name": user_name,
            "user_email": user_email,
            "order_id": order_id[-6:].upper(),
            "result_link": result_link,
            "service_label": service_label,
        },
    }
    try:
        requests.post(
            "https://api.emailjs.com/api/v1.0/email/send",
            json=payload,
            timeout=15,
        )
    except Exception as exc:
        print(f"⚠️ Email: {exc}")


def _complete_order_with_video(doc, local_vid) -> bool:
    r2_url = upload_to_r2(local_vid)
    if not r2_url:
        return False
    db.collection("orders").document(doc.id).update({
        "status": "completed",
        "resultLink": r2_url,
        "renderProvider": kling.RENDER_PROVIDER_KLING,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    print(f"✅ TRẢ HÀNG {doc.id}")
    try:
        data = doc.to_dict() or {}
        send_telegram_message(
            f"✅ <b>HOÀN TẤT</b>\n🆔 #{doc.id[-6:].upper()}\n"
            f"👤 {data.get('userName', '?')}\n"
            f"📹 <a href=\"{r2_url}\">Video</a>"
        )
    except Exception:
        pass
    try:
        send_completion_email(doc.id, doc.to_dict() or {}, r2_url)
    except Exception:
        pass
    if os.path.exists(local_vid):
        os.remove(local_vid)
    _pop_processing_cache(doc.id)
    return True


def on_processing_orders_snapshot(snapshot, changes, read_time) -> None:
    with _processing_cache_lock:
        fresh = {}
        for doc in snapshot:
            d = doc.to_dict() or {}
            if d.get("status") == "processing":
                fresh[doc.id] = doc
        _processing_cache.clear()
        _processing_cache.update(fresh)


def start_processing_listener() -> None:
    db.collection("orders").where(
        filter=FieldFilter("status", "==", "processing")
    ).on_snapshot(on_processing_orders_snapshot)
    print("👂 Listener processing orders")


def _ensure_pending_worker() -> None:
    global _pending_worker_started
    with _pending_queue_lock:
        if _pending_worker_started:
            return
        _pending_worker_started = True
        threading.Thread(target=_pending_order_worker, daemon=True).start()


def _pending_order_worker() -> None:
    while True:
        order_id = None
        with _pending_queue_lock:
            if _pending_order_queue:
                order_id = _pending_order_queue.pop(0)
        if order_id:
            if not _should_bot_process_order(order_id):
                continue
            try:
                kling.submit_order(order_id)
            except Exception as exc:
                print(f"❌ Nạp đơn {order_id}: {exc}")
                _session_error_backoff[order_id] = time.time() + SESSION_ERROR_BACKOFF_SEC
        else:
            time.sleep(0.5)


def on_pending_orders_snapshot(keys, changes, read_time) -> None:
    if not is_bot_enabled():
        return
    _ensure_pending_worker()
    with _pending_queue_lock:
        for ch in changes:
            if ch.type.name != "ADDED":
                continue
            oid = ch.document.id
            with _submitting_orders_lock:
                if oid in _submitting_orders:
                    continue
            if not _should_bot_process_order(oid):
                continue
            if oid not in _pending_order_queue:
                _pending_order_queue.append(oid)
                print(f"📋 Xếp hàng: {oid}")


def _enqueue_pending_rescan() -> None:
    if not is_bot_enabled():
        return
    _ensure_pending_worker()
    try:
        for doc in db.collection("orders").where(
            filter=FieldFilter("status", "==", "pending")
        ).limit(20).stream():
            oid = doc.id
            if _pending_submit_backoff_active(oid):
                continue
            with _submitting_orders_lock:
                if oid in _submitting_orders:
                    continue
            if not _should_bot_process_order(oid):
                continue
            with _pending_queue_lock:
                if oid not in _pending_order_queue:
                    _pending_order_queue.append(oid)
    except Exception as exc:
        print(f"⚠️ rescan pending: {exc}")


def check_finished_orders() -> None:
    if not is_bot_enabled():
        return
    with _processing_cache_lock:
        cache = dict(_processing_cache)
    eligible = kling.processing_eligible(cache)
    if not eligible:
        return
    print(f"\n🔍 Poll recovery Kling: {len(eligible)} đơn...")
    kling.poll_kling_orders(eligible)


def _rescan_pending_orders_loop() -> None:
    while True:
        time.sleep(SESSION_ERROR_BACKOFF_SEC)
        _enqueue_pending_rescan()


def start_bot() -> None:
    global BOT_NAME
    parser = argparse.ArgumentParser(description="Kaling bot — Kling Motion Control only")
    parser.add_argument("--name", required=True, help="Tên bot (vd: kling_vps_bot)")
    args = parser.parse_args()

    BOT_NAME = normalize_bot_name(args.name)
    if not BOT_NAME:
        print("❌ Tên bot không hợp lệ")
        sys.exit(1)
    if not kling.enabled_for_bot(BOT_NAME):
        print(f"⚠️ Tên bot '{BOT_NAME}' không chứa 'kling' — vẫn chạy engine Kling")

    print(f"📡 Kaling BOT [{BOT_NAME}] — Kling 2.6 / 720p / Matches Video")

    kling.wire(
        db=db,
        bot_name=BOT_NAME,
        print=print,
        is_bot_enabled=is_bot_enabled,
        pending_submit_backoff_active=_pending_submit_backoff_active,
        submitting_orders_lock=_submitting_orders_lock,
        submitting_orders=_submitting_orders,
        browser_lock=browser_lock,
        download_file=download_file,
        complete_order_with_video=_complete_order_with_video,
        notify_internal_error_telegram=notify_internal_error_telegram,
        send_telegram_message=send_telegram_message,
        pop_processing_cache=_pop_processing_cache,
        skip_if_order_done=_skip_if_order_done,
        session_error_backoff=_session_error_backoff,
    )

    start_bot_control_listener()
    start_processing_listener()
    kling.log_accounts_on_startup()

    def monitor_loop() -> None:
        while True:
            if is_bot_enabled():
                check_finished_orders()
            sleep = int(get_env("BOT_POLL_ACTIVE_SEC", "90"))
            with _processing_cache_lock:
                if not _processing_cache:
                    sleep = int(get_env("BOT_POLL_IDLE_SEC", "300"))
            time.sleep(sleep)

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=_rescan_pending_orders_loop, daemon=True).start()

    db.collection("orders").where(
        filter=FieldFilter("status", "==", "pending")
    ).on_snapshot(on_pending_orders_snapshot)
    _enqueue_pending_rescan()

    print(f"🟢 [{BOT_NAME}] Trực — Firestore pending → Kling Playwright")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    start_bot()
