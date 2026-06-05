"""
XiaoYang web multi-account + Aidancing fallback cho motionai (web1).
Gọi xy_wire() từ bot.py khi khởi động.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone

import requests
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from project_env import get_env, load_project_env
from xiaoyang_web import XiaoyangAuthError, XiaoyangWebClient, XiaoyangWebError

load_project_env()

RENDER_PROVIDER_AIDANCING = "aidancing"
RENDER_PROVIDER_XIAOYANG = "xiaoyang"
AIDANCING_TURBO_MODEL_IDS = frozenset({"117"})
AIDANCING_FAST_MODEL_IDS = frozenset({"124", "125"})
XIAOYANG_MODAL_STANDARD = "motion_v26"
XIAOYANG_MODAL_TURBO = "motion_v30"
XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT = int(get_env("XIAOYANG_MAX_CONCURRENT", "4"))

USER_NOTE_ORDER_FAILED = "Đơn hàng xử lý không thành công, hệ thống đã hoàn lại coin."
USER_NOTE_FILES_MISSING = "Ảnh hoặc video quý khách tải lên không tồn tại, hệ thống đã hoàn lại coin."

_g: dict = {}
_active_render_provider = RENDER_PROVIDER_XIAOYANG
_active_render_provider_lock = threading.Lock()
_xy_web_clients: dict = {}
_xy_web_clients_lock = threading.Lock()
_xy_inflight: dict = {}
_xy_inflight_lock = threading.Lock()
_xy_accounts_cache = None
_xy_accounts_cache_lock = threading.Lock()


def wire(**kwargs):
    _g.update(kwargs)


def enabled_for_bot(bot_name: str | None) -> bool:
    return bool(bot_name and "motionai" in bot_name.lower())


def get_active_render_provider():
    with _active_render_provider_lock:
        return _active_render_provider


def apply_render_provider_from_bot_data(data: dict, source=""):
    global _active_render_provider
    p = (data.get("activeRenderProvider") or data.get("activeProvider") or RENDER_PROVIDER_XIAOYANG)
    p = p.strip().lower()
    if p not in (RENDER_PROVIDER_AIDANCING, RENDER_PROVIDER_XIAOYANG):
        p = RENDER_PROVIDER_XIAOYANG
    with _active_render_provider_lock:
        prev = _active_render_provider
        _active_render_provider = p
    if p != prev:
        suffix = f" ({source})" if source else ""
        print(f"\n🔀 Render provider: {prev} → {p}{suffix} (đơn đang chạy giữ engine cũ)\n")


def start_render_provider_listener():
    db = _g["db"]
    bot_name = _g["bot_name"]
    initial = RENDER_PROVIDER_XIAOYANG
    bot_doc = db.collection("bots").document(bot_name).get()
    if bot_doc.exists:
        apply_render_provider_from_bot_data(bot_doc.to_dict() or {})
        initial = get_active_render_provider()
    _g["print"](f"🎬 Render provider (đơn mới): {initial}")


def _xiaoyang_account_id(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def load_xiaoyang_accounts():
    global _xy_accounts_cache
    with _xy_accounts_cache_lock:
        if _xy_accounts_cache is not None:
            return _xy_accounts_cache
        accounts = []
        raw = (get_env("XIAOYANG_ACCOUNTS") or "").strip()
        if raw:
            if raw.startswith("["):
                import json as _json
                try:
                    for item in _json.loads(raw):
                        email = (item.get("email") or "").strip()
                        password = item.get("password") or ""
                        if email and password:
                            accounts.append({
                                "id": _xiaoyang_account_id(email),
                                "email": email,
                                "password": password,
                            })
                except Exception as e:
                    print(f"⚠️ XIAOYANG_ACCOUNTS JSON lỗi: {e}")
            else:
                for part in raw.split(","):
                    part = part.strip()
                    if ":" not in part:
                        continue
                    email, password = part.split(":", 1)
                    email, password = email.strip(), password.strip()
                    if email and password:
                        accounts.append({
                            "id": _xiaoyang_account_id(email),
                            "email": email,
                            "password": password,
                        })
        if not accounts:
            email = (get_env("XIAOYANG_EMAIL") or "").strip()
            password = get_env("XIAOYANG_PASSWORD") or ""
            if email and password:
                accounts.append({
                    "id": _xiaoyang_account_id(email),
                    "email": email,
                    "password": password,
                })
        _xy_accounts_cache = accounts
        return accounts


def _get_xy_web_client(account_id: str) -> XiaoyangWebClient:
    key = account_id.lower()
    with _xy_web_clients_lock:
        if key not in _xy_web_clients:
            _xy_web_clients[key] = XiaoyangWebClient(account_id=key)
        return _xy_web_clients[key]


def _reset_xy_web_client(account_id: str | None = None):
    with _xy_web_clients_lock:
        if account_id:
            _xy_web_clients.pop(account_id.lower(), None)
        else:
            _xy_web_clients.clear()


def _ensure_xy_web_session(client: XiaoyangWebClient, email=None, password=None):
    try:
        return client.me()
    except XiaoyangAuthError:
        client.login(email=email, password=password)
        return client.me()


def _xy_inflight_inc(account_id: str):
    with _xy_inflight_lock:
        _xy_inflight[account_id] = _xy_inflight.get(account_id, 0) + 1


def _xy_inflight_dec(account_id: str):
    with _xy_inflight_lock:
        n = _xy_inflight.get(account_id, 0) - 1
        if n <= 0:
            _xy_inflight.pop(account_id, None)
        else:
            _xy_inflight[account_id] = n


def _count_xy_processing_for_account(account_id: str) -> int:
    db = _g["db"]
    cache = _g.get("processing_cache", {})
    cache_lock = _g["processing_cache_lock"]
    cache_count = 0
    with cache_lock:
        for doc in cache.values():
            d = doc.to_dict() or {}
            if d.get("status") == "processing" and d.get("xiaoyangAccount") == account_id:
                cache_count += 1
    try:
        q = db.collection("orders").where(
            filter=FieldFilter("status", "==", "processing")
        ).where(
            filter=FieldFilter("xiaoyangAccount", "==", account_id)
        )
        db_count = sum(1 for _ in q.stream())
        return max(cache_count, db_count)
    except Exception as e:
        print(f"⚠️ Đếm đơn XiaoYang nick {account_id}: {e}")
        return cache_count


def _xy_active_count(account_id: str) -> int:
    with _xy_inflight_lock:
        inflight = _xy_inflight.get(account_id, 0)
    return _count_xy_processing_for_account(account_id) + inflight


def _pick_xiaoyang_account():
    accounts = load_xiaoyang_accounts()
    if not accounts:
        return None
    best = None
    best_count = XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT
    for acc in accounts:
        c = _xy_active_count(acc["id"])
        if c < XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT and c < best_count:
            best = acc
            best_count = c
    return best


def _account_lookup(account_id: str):
    for acc in load_xiaoyang_accounts():
        if acc["id"] == account_id:
            return acc
    return None


def _xiaoyang_modal_for_order(order_data: dict) -> tuple[str, str]:
    model_id = str(order_data.get("modelId") or "").strip()
    if model_id in AIDANCING_TURBO_MODEL_IDS:
        return XIAOYANG_MODAL_TURBO, get_env("XIAOYANG_OPTION_KEY", "default")
    if model_id in AIDANCING_FAST_MODEL_IDS or not model_id:
        return XIAOYANG_MODAL_STANDARD, get_env("XIAOYANG_OPTION_KEY", "default")
    modal = get_env("XIAOYANG_MODAL_KEY", XIAOYANG_MODAL_STANDARD)
    if modal not in (XIAOYANG_MODAL_STANDARD, XIAOYANG_MODAL_TURBO):
        modal = XIAOYANG_MODAL_STANDARD
    return modal, get_env("XIAOYANG_OPTION_KEY", "default")


def _order_render_provider(order_data: dict) -> str:
    if not order_data:
        return RENDER_PROVIDER_AIDANCING
    rp = (order_data.get("renderProvider") or "").strip().lower()
    if rp in (RENDER_PROVIDER_AIDANCING, RENDER_PROVIDER_XIAOYANG):
        return rp
    if order_data.get("xiaoyangTaskId"):
        return RENDER_PROVIDER_XIAOYANG
    return RENDER_PROVIDER_AIDANCING


def split_monitor_state(processing_cache: dict, min_render_sec: int):
    now = datetime.now(timezone.utc)
    ad_eligible = []
    xy_eligible = []
    for doc in processing_cache.values():
        d = doc.to_dict() or {}
        if d.get("status") != "processing":
            continue
        submitted_at = d.get("submittedAt")
        if submitted_at and (now - submitted_at).total_seconds() <= min_render_sec:
            continue
        if _order_render_provider(d) == RENDER_PROVIDER_XIAOYANG and d.get("xiaoyangTaskId"):
            xy_eligible.append(doc)
        else:
            job_id = d.get("aidancingJobId")
            if job_id and job_id != "MANUAL":
                ad_eligible.append(doc)
    return ad_eligible, xy_eligible


def _fail_order_processing(doc, order_data, err_detail, system_note, context: str):
    db = _g["db"]
    _g["notify_internal_error_telegram"](doc.id, order_data, err_detail, context)
    cost_coins = order_data.get("costCoins", 0)
    user_id = order_data.get("userId")
    if cost_coins > 0 and user_id:
        try:
            db.collection("users").document(user_id).update({"coins": firestore.Increment(cost_coins)})
        except Exception as e:
            print(f"⚠️ Hoàn coin lỗi: {e}")
    db.collection("orders").document(doc.id).update({
        "status": "failed",
        "adminNote": firestore.DELETE_FIELD,
        "systemNote": system_note,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    pop = _g.get("pop_processing_cache")
    if pop:
        pop(doc.id)


def _mark_order_processing(doc_ref, job_id, *, provider, xiaoyang_account=None, xiaoyang_account_email=None):
    payload = {
        "status": "processing",
        "renderProvider": provider,
        "submittedAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if provider == RENDER_PROVIDER_XIAOYANG:
        payload["xiaoyangTaskId"] = str(job_id)
        payload["xiaoyangSubmitMode"] = "web"
        if xiaoyang_account:
            payload["xiaoyangAccount"] = str(xiaoyang_account)
        if xiaoyang_account_email:
            payload["xiaoyangAccountEmail"] = str(xiaoyang_account_email)
    else:
        payload["aidancingJobId"] = str(job_id)
    doc_ref.update(payload)


def submit_to_xiaoyang(order_id: str, account: dict) -> bool:
    if not _g["is_bot_enabled"]():
        return False
    if _g["pending_submit_backoff_active"](order_id):
        return False
    submitting_lock = _g["submitting_orders_lock"]
    submitting = _g["submitting_orders"]
    with submitting_lock:
        if order_id in submitting:
            return False
        submitting.add(order_id)

    account_id = account["id"]
    account_email = account.get("email", "")
    _xy_inflight_inc(account_id)
    success = False
    try:
        with _g["browser_lock"]:
            db = _g["db"]
            doc_ref = db.collection("orders").document(order_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            if data.get("status") != "pending":
                return False

            nick_label = account_email or account_id
            print(f"\n⚡ [NẠP ĐƠN / XiaoYang Web] {order_id} — nick {nick_label}...")
            img_url = (data.get("characterImageLink") or "").strip()
            vid_url = (data.get("referenceVideoLink") or "").strip()
            if not img_url or not vid_url:
                _fail_order_processing(
                    doc, data,
                    "Thiếu characterImageLink hoặc referenceVideoLink",
                    USER_NOTE_FILES_MISSING,
                    "submit xiaoyang",
                )
                return False

            char_path = None
            vid_path = None
            download_file = _g["download_file"]
            try:
                modal, option = _xiaoyang_modal_for_order(data)
                prompt = (data.get("prompt") or get_env(
                    "XIAOYANG_PROMPT", "Follow the reference motion naturally"
                )).strip()
                tier = "Turbo/v3.0" if modal == XIAOYANG_MODAL_TURBO else "Thường/v2.6"
                enhance_4k = get_env("XIAOYANG_ENHANCE_4K", "1").strip().lower() not in ("0", "false", "no")
                hd = " + HD 2K" if enhance_4k else ""
                api = _get_xy_web_client(account_id)
                _ensure_xy_web_session(api, account_email, account.get("password"))
                print(
                    f"🚀 [XiaoYang Web/{nick_label}] {tier}{hd} — "
                    f"modelId={data.get('modelId')} → {modal}/{option}..."
                )
                for attempt in range(1, 3):
                    if attempt > 1:
                        print(f"🔄 Thử tải file lần {attempt}...")
                    char_path = download_file(img_url, f"char_{order_id}.png")
                    vid_path = download_file(vid_url, f"vid_{order_id}.mp4")
                    if char_path and vid_path:
                        break
                    time.sleep(2)
                if not char_path or not vid_path:
                    raise XiaoyangWebError("Không tải được ảnh/video từ link đơn hàng")
                print("📤 Upload ảnh lên xiaoyang.online...")
                image_token = api.upload_file(char_path)
                print("📤 Upload video motion...")
                video_token = api.upload_file(vid_path)
                resp = api.create_motion_task(
                    image_token=image_token,
                    video_token=video_token,
                    prompt=prompt,
                    modal_key=modal,
                    option_key=option,
                    motion_orientation=get_env("XIAOYANG_MOTION_ORIENTATION", "video"),
                    enhance_4k=enhance_4k,
                )
                task_id = resp.get("task_id")
                if not task_id:
                    raise XiaoyangWebError(f"Không có task_id: {resp}")
                print(f"🆔 [XiaoYang/{nick_label}] task: {task_id} ({resp.get('status')})")
                _mark_order_processing(
                    doc_ref, task_id,
                    provider=RENDER_PROVIDER_XIAOYANG,
                    xiaoyang_account=account_id,
                    xiaoyang_account_email=account_email,
                )
                _g["session_error_backoff"].pop(order_id, None)
                print(f"✅ Đơn {order_id} → processing (XiaoYang Web, {nick_label})")
                try:
                    short_id = order_id[-6:].upper()
                    _g["send_telegram_message"](
                        f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b> (XiaoYang)\n\n"
                        f"🆔 Mã đơn: #{short_id}\n"
                        f"📧 Nick: {nick_label}\n"
                        f"🤖 Task: <code>{task_id}</code>\n"
                        f"⏳ Poll sau {_g['min_render_sec'] // 60} phút..."
                    )
                except Exception:
                    pass
                success = True
            except (requests.RequestException, XiaoyangAuthError, XiaoyangWebError, ValueError) as e:
                print(f"❌ Nạp XiaoYang thất bại {order_id} ({nick_label}): {e}")
                if isinstance(e, XiaoyangAuthError):
                    _reset_xy_web_client(account_id)
                _g["notify_internal_error_telegram"](order_id, data, str(e), f"submit xiaoyang/{nick_label}")
            finally:
                if char_path and os.path.exists(char_path):
                    os.remove(char_path)
                if vid_path and os.path.exists(vid_path):
                    os.remove(vid_path)
    finally:
        _xy_inflight_dec(account_id)
        with submitting_lock:
            submitting.discard(order_id)
    return success


def submit_order(order_id: str):
    if get_active_render_provider() != RENDER_PROVIDER_XIAOYANG:
        _g["submit_to_aidancing"](order_id)
        return
    account = _pick_xiaoyang_account()
    if not account:
        print(
            f"📊 XiaoYang đầy slot ({XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT} đơn/nick) "
            f"→ Aidancing {order_id}"
        )
        _g["submit_to_aidancing"](order_id, fallback_reason="xiaoyang_queue_full")
        return
    if submit_to_xiaoyang(order_id, account):
        return
    print(f"⚠️ XiaoYang thất bại {order_id} → Aidancing")
    _g["submit_to_aidancing"](order_id, fallback_reason="xiaoyang_fail")


def poll_xiaoyang_orders(orders_to_check):
    skip_done = _g.get("skip_if_order_done")
    complete = _g["complete_order_with_video"]
    for doc in orders_to_check:
        order_data = doc.to_dict() or {}
        task_id = str(order_data.get("xiaoyangTaskId") or "").strip()
        if not task_id:
            continue
        account_id = (order_data.get("xiaoyangAccount") or "").strip()
        acc = _account_lookup(account_id) if account_id else None
        nick = (order_data.get("xiaoyangAccountEmail") or account_id or "?")
        print(f"🧐 XiaoYang Web — task {task_id} (đơn {doc.id}, {nick})...")
        try:
            api = _get_xy_web_client(account_id or "default")
            if acc:
                _ensure_xy_web_session(api, acc["email"], acc["password"])
            else:
                _ensure_xy_web_session(api)
            t = api.get_task(task_id)
        except (XiaoyangAuthError, XiaoyangWebError) as e:
            print(f"❌ Poll XiaoYang {task_id}: {e}")
            if isinstance(e, XiaoyangAuthError) and account_id:
                _reset_xy_web_client(account_id)
            continue
        st = (t.get("status") or "").upper()
        err = t.get("error_message")
        stage = ""
        if t.get("enhance_4k") and t.get("enhance_stage") == "enhancing" and st != "SUCCESS":
            stage = " (HD 2K)"
        print(f"   status={st}{stage}" + (f" — {err}" if err else ""))
        if st == "SUCCESS":
            if skip_done and skip_done(doc.id, "đã completed"):
                continue
            print(f"🎉 XiaoYang task {task_id} HOÀN TẤT — tải video...")
            try:
                local_vid = api.download_task_file(task_id, f"res_{doc.id}.mp4")
                complete(doc, local_vid)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
        elif st == "FAIL":
            _fail_order_processing(
                doc, order_data,
                f"XiaoYang task {task_id} FAIL: {err or ''}",
                USER_NOTE_ORDER_FAILED,
                "render xiaoyang",
            )
        else:
            print(f"⏳ Task {task_id} vẫn {st}")


def log_accounts_on_startup():
    accounts = load_xiaoyang_accounts()
    hd = "bật" if get_env("XIAOYANG_ENHANCE_4K", "1").strip().lower() not in ("0", "false", "no") else "tắt"
    print(
        f"👥 XiaoYang accounts: {len(accounts)} nick | "
        f"max {XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT} đơn/nick | HD 2K: {hd}"
    )
    for acc in accounts:
        try:
            xy = _get_xy_web_client(acc["id"])
            me = _ensure_xy_web_session(xy, acc["email"], acc["password"])
            active = _xy_active_count(acc["id"])
            print(
                f"  ✅ {acc['email']} | credits: {me.get('credits', '?')} | "
                f"đang chạy: {active}/{XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT}"
            )
        except Exception as e:
            print(f"  ⚠️  {acc['email']}: {e}")
