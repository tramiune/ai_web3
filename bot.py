import time
import os
import sys
import re
import base64
import argparse
import socket
import queue
import requests
import firebase_admin
import threading
from datetime import datetime, timezone
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from playwright.sync_api import sync_playwright
from project_env import get_env, load_project_env

load_project_env()

from aidancing_api import AidancingApiClient, SessionExpiredError
import xiaoyang_motion as xy_motion
from xiaoyang_api import (
    XiaoyangApiClient,
    XiaoyangAuthError,
    XiaoyangApiError,
    load_api_keys,
)
from xiaoyang_direct import DirectMediaError, upload_result_file
from xiaoyang_media import MediaValidationError

# --- CONFIGURATION ---
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Tên bot: bắt buộc khi chạy — python bot.py --name aidancing-vps1
BOT_NAME = None
bot_enabled = False
bot_enabled_lock = threading.Lock()

def is_bot_enabled():
    with bot_enabled_lock:
        return bot_enabled

def set_bot_enabled(value):
    global bot_enabled
    with bot_enabled_lock:
        bot_enabled = bool(value)

# CREATE_URL đã được chuyển thành dynamic theo modelId trong đơn hàng
AIDANCING_ORIGIN = "https://aidancing.net"
DASHBOARD_URL = f"{AIDANCING_ORIGIN}/dashboard"
WORKER_URL = "https://motionai-upload-api.traderfinn0312.workers.dev"
BOT_CHROME_PROFILE = os.path.abspath(os.environ.get("BOT_CHROME_PROFILE", "bot_chrome_profile"))

browser_lock = threading.Lock()
submit_lock = threading.Lock()  # HTTP nạp đơn — tách khỏi poll (browser_lock chỉ Playwright)
_processing_cache_refresh_at = 0.0
_pending_order_queue = []
_pending_queue_lock = threading.Lock()
_pending_worker_started = False
_submitting_orders = set()
_submitting_orders_lock = threading.Lock()
MIN_RENDER_SEC = int(os.environ.get("BOT_MIN_RENDER_SEC", "600"))
RENDER_PROVIDER_AIDANCING = "aidancing"
RENDER_PROVIDER_XIAOYANG = "xiaoyang"
RENDER_PROVIDER_VIDEOAIEASY = "videoaieasy"
RENDER_PROVIDER_TOOL98 = "tool98"
_RENDER_PROVIDERS = (
    RENDER_PROVIDER_AIDANCING,
    RENDER_PROVIDER_XIAOYANG,
    RENDER_PROVIDER_VIDEOAIEASY,
    RENDER_PROVIDER_TOOL98,
)
AIDANCING_TURBO_MODEL_IDS = frozenset({"117"})
AIDANCING_FAST_MODEL_IDS = frozenset({"124", "125"})
XIAOYANG_MODAL_STANDARD = "motion_v26"
XIAOYANG_MODAL_TURBO = "motion_v30"
from user_order_notes import (
    USER_NOTE_FILES_MISSING,
    USER_NOTE_ORDER_FAILED,
    USER_NOTE_SUBMIT_FAILED,
    USER_NOTE_VIDEO_INVALID,
    user_note_for_media_validation,
    user_note_for_render_failure,
)

USER_NOTE_FILES_INVALID = USER_NOTE_VIDEO_INVALID
_active_render_provider = RENDER_PROVIDER_XIAOYANG
_active_render_provider_lock = threading.Lock()
_processing_cache = {}
_processing_cache_lock = threading.Lock()
_xy_clients = {}
_xy_clients_lock = threading.Lock()
_xy_credits_cache = {}
_xy_credits_cache_lock = threading.Lock()
XY_CREDITS_CACHE_TTL = int(os.environ.get("XIAOYANG_CREDITS_CACHE_SEC", "120"))
_http_client = None
_http_client_lock = threading.Lock()


def _pop_processing_cache(order_id):
    with _processing_cache_lock:
        _processing_cache.pop(order_id, None)


def _order_already_completed(order_id):
    try:
        snap = db.collection('orders').document(order_id).get()
        if not snap.exists:
            return True
        d = snap.to_dict() or {}
        return d.get('status') == 'completed' or bool(d.get('resultLink'))
    except Exception as e:
        print(f"⚠️ Không đọc được đơn {order_id}: {e}")
        return False


def _skip_if_order_done(order_id, reason):
    if _order_already_completed(order_id):
        print(f"⏭️ Bỏ qua đơn {order_id} — {reason}")
        _pop_processing_cache(order_id)
        return True
    return False


def get_active_render_provider():
    with _active_render_provider_lock:
        return _active_render_provider


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
    if rp in _RENDER_PROVIDERS:
        return rp
    if order_data.get("tool98JobId"):
        return RENDER_PROVIDER_TOOL98
    if order_data.get("videoaieasyJobId"):
        return RENDER_PROVIDER_VIDEOAIEASY
    if order_data.get("xiaoyangTaskId"):
        return RENDER_PROVIDER_XIAOYANG
    return RENDER_PROVIDER_AIDANCING


def _order_xy_key_index(order_data: dict) -> int:
    if not order_data:
        return 0
    raw = order_data.get("xiaoyangKeyIndex")
    if raw is not None:
        try:
            i = int(raw)
            if i >= 0:
                return i
        except (TypeError, ValueError):
            pass
    return 0


def _xy_credit_required(model_id: str) -> int:
    if str(model_id or "").strip() in AIDANCING_TURBO_MODEL_IDS:
        return int(get_env("XIAOYANG_MIN_CREDITS_TURBO", "220"))
    return int(get_env("XIAOYANG_MIN_CREDITS_FAST", "80"))


def _count_xy_active_per_key() -> dict[int, int]:
    counts: dict[int, int] = {}
    with _processing_cache_lock:
        for doc in _processing_cache.values():
            d = doc.to_dict() or {}
            if _order_render_provider(d) != RENDER_PROVIDER_XIAOYANG:
                continue
            if not d.get("xiaoyangTaskId"):
                continue
            ki = _order_xy_key_index(d)
            counts[ki] = counts.get(ki, 0) + 1
    return counts


def _invalidate_xy_key(key_index: int):
    with _xy_clients_lock:
        _xy_clients.pop(key_index, None)
    with _xy_credits_cache_lock:
        _xy_credits_cache.pop(key_index, None)


def _get_xy_client(key_index: int) -> XiaoyangApiClient:
    keys = load_api_keys()
    if not keys:
        raise ValueError("Thiếu XIAOYANG_API_KEYS")
    if key_index < 0 or key_index >= len(keys):
        key_index = 0
    with _xy_clients_lock:
        client = _xy_clients.get(key_index)
        if client is None:
            client = XiaoyangApiClient(api_key=keys[key_index])
            _xy_clients[key_index] = client
        return client


def _xy_key_credits(key_index: int, *, force: bool = False) -> tuple[int, str]:
    now = time.time()
    if not force:
        with _xy_credits_cache_lock:
            cached = _xy_credits_cache.get(key_index)
            if cached and now - cached[2] < XY_CREDITS_CACHE_TTL:
                return cached[0], cached[1]
    me = _get_xy_client(key_index).me()
    credits = int(me.get("credits") or 0)
    email = str(me.get("email") or "?")
    with _xy_credits_cache_lock:
        _xy_credits_cache[key_index] = (credits, email, now)
    return credits, email


def _pick_xiaoyang_key_index(order_data: dict) -> int:
    """Chọn key: đủ credit cho gói + ít đơn XY processing nhất (tie → credit cao hơn)."""
    keys = load_api_keys()
    if len(keys) <= 1:
        return 0
    model_id = str(order_data.get("modelId") or "").strip()
    required = _xy_credit_required(model_id)
    active = _count_xy_active_per_key()
    candidates = []
    for i in range(len(keys)):
        try:
            credits, email = _xy_key_credits(i)
        except Exception as e:
            print(f"⚠️ XY key #{i} không đọc được credit: {e}")
            continue
        if credits < required:
            continue
        candidates.append((active.get(i, 0), -credits, i, email, credits))
    if not candidates:
        raise XiaoyangApiError(
            f"Không có API key XY đủ credit (cần ≥{required}, modelId={model_id or 'fast'})"
        )
    candidates.sort()
    load, _, idx, email, credits = candidates[0]
    print(
        f"🔑 XY key #{idx} ({email}, {credits} CR, {load} đơn đang chạy) "
        f"— trong {len(keys)} key"
    )
    return idx


def _xy_account_label(key_index: int) -> str:
    """Nhãn nick XY cho Telegram admin (email + slot key)."""
    try:
        credits, email = _xy_key_credits(key_index)
        return f"{email} (key #{key_index}, {credits} CR)"
    except Exception:
        return f"key #{key_index}"


def _get_http_client():
    global _http_client
    with _http_client_lock:
        if _http_client is None:
            _http_client = AidancingApiClient()
        return _http_client


def _reset_http_client():
    global _http_client
    with _http_client_lock:
        _http_client = None


def _http_create_job(model_id, char_path, vid_path):
    api = _get_http_client()
    return api.create_job(model_id, char_path, vid_path)


def _http_poll_orders(orders_to_check):
    api = _get_http_client()
    job_ids = [str(doc.to_dict().get('aidancingJobId')) for doc in orders_to_check]
    jobs_map = api.find_jobs_by_ids(job_ids)
    for doc in orders_to_check:
        job_id = str(doc.to_dict().get('aidancingJobId'))
        print(f"🧐 API — Job {job_id}...")
        job = jobs_map.get(int(job_id))
        if not job:
            print(f"❌ Không thấy job {job_id} trong API (3 trang đầu)")
            continue
        status = (job.get('status') or '').upper()
        print(f"   status={status}, outputFileId={job.get('outputFileId')}")
        if status == 'COMPLETED' and job.get('outputFileId'):
            if _skip_if_order_done(doc.id, "đã completed trên Firestore"):
                continue
            print(f"🎉 Job {job_id} HOÀN TẤT — tải file {job['outputFileId']}...")
            try:
                local_vid = api.download_file(job['outputFileId'], f"res_{doc.id}.mp4")
                _complete_order_with_video(doc, local_vid)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
        elif status in ('FAILED', 'ERROR', 'CANCELLED'):
            print(f"❌ Job {job_id} thất bại trên aidancing ({status})")
            order_data = doc.to_dict()
            err_detail = f'Aidancing job {job_id} {status}: {job.get("errorMessage") or ""}'
            _fail_order_processing(
                doc, order_data, err_detail,
                user_note_for_render_failure(job.get("errorMessage")),
                'render aidancing',
            )
        else:
            print(f"⏳ Job {job_id} vẫn {status}")


def _normalize_render_provider(value, default=RENDER_PROVIDER_XIAOYANG):
    p = (value or default).strip().lower()
    if p not in _RENDER_PROVIDERS:
        return default
    return p


def _apply_render_provider(provider, source=""):
    global _active_render_provider
    provider = _normalize_render_provider(provider)
    with _active_render_provider_lock:
        prev = _active_render_provider
        _active_render_provider = provider
    if provider != prev:
        suffix = f" ({source})" if source else ""
        print(f"\n🔀 Render provider: {prev} → {provider}{suffix} (đơn đang chạy giữ engine cũ)\n")
    return provider


def _render_provider_from_bot_data(data: dict) -> str:
    if not data:
        return RENDER_PROVIDER_XIAOYANG
    return _normalize_render_provider(
        data.get("activeRenderProvider") or data.get("activeProvider")
    )


def start_render_provider_listener():
    initial = RENDER_PROVIDER_XIAOYANG
    bot_doc = db.collection("bots").document(BOT_NAME).get()
    if bot_doc.exists:
        initial = _render_provider_from_bot_data(bot_doc.to_dict() or {})
    else:
        legacy = db.collection("settings").document("render").get()
        if legacy.exists:
            initial = _normalize_render_provider(
                (legacy.to_dict() or {}).get("activeProvider")
            )
    _apply_render_provider(initial)
    print(f"🎬 Render provider (đơn mới): {initial}")


def _fail_order_processing(doc, order_data, err_detail, system_note, context: str):
    if xy_motion.enabled_for_bot(BOT_NAME):
        if xy_motion.fail_or_tool98_fallback(doc, order_data, err_detail, system_note, context):
            return
    notify_internal_error_telegram(doc.id, order_data, err_detail, context)
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
    _pop_processing_cache(doc.id)


def _http_poll_xiaoyang_orders(orders_to_check):
    for doc in orders_to_check:
        d = doc.to_dict() or {}
        task_id = str(d.get("xiaoyangTaskId") or "").strip()
        if not task_id:
            continue
        key_idx = _order_xy_key_index(d)
        api = _get_xy_client(key_idx)
        print(f"🧐 XiaoYang key#{key_idx} — task {task_id} (đơn {doc.id})...")
        try:
            t = api.get_task(task_id)
        except (XiaoyangAuthError, XiaoyangApiError) as e:
            print(f"❌ Poll XiaoYang {task_id}: {e}")
            if "401" in str(e) or "403" in str(e):
                _invalidate_xy_key(key_idx)
            continue
        st = (t.get("status") or "").upper()
        err = t.get("error_message")
        print(f"   status={st}" + (f" — {err}" if err else ""))
        if st == "SUCCESS":
            if _skip_if_order_done(doc.id, "đã completed trên Firestore"):
                continue
            print(f"🎉 XiaoYang task {task_id} HOÀN TẤT — tải video...")
            try:
                local_vid = api.download_task(task_id, f"res_{doc.id}.mp4")
                if _complete_order_with_video(doc, local_vid):
                    api.try_delete_task(task_id)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
        elif st == "FAIL":
            order_data = doc.to_dict() or {}
            print(f"❌ Task {task_id} FAIL trên XiaoYang")
            _fail_order_processing(
                doc,
                order_data,
                f"XiaoYang task {task_id} FAIL: {err or ''}",
                user_note_for_render_failure(err),
                "render xiaoyang",
            )
            api.try_delete_task(task_id)
        else:
            print(f"⏳ Task {task_id} vẫn {st}")


class PersistentApiPool:
    """Giữ 1 kết nối CDP + 1 tab nền suốt phiên bot — không mở/đóng Chrome mỗi lần poll."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._api = None

    def get(self):
        if self._api is not None and self._api._page_alive():
            return self._api
        self.reset()
        self._playwright = sync_playwright().start()
        self._browser = launch_aidancing_browser(self._playwright)
        self._api = AidancingApiClient(self._browser.context, persistent=True)
        print("🔌 Session API cố định — 1 tab nền (fetch API, không reload dashboard)")
        return self._api

    def reset(self):
        if self._api:
            try:
                self._api.shutdown()
            except Exception:
                pass
        self._api = None
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None


_api_pool = PersistentApiPool()

_pw_queue = queue.Queue()
_pw_worker_started = False
_pw_worker_lock = threading.Lock()
_pw_worker_tid = None


def _ensure_playwright_worker():
    global _pw_worker_started
    with _pw_worker_lock:
        if _pw_worker_started:
            return
        _pw_worker_started = True
        threading.Thread(
            target=_playwright_worker_loop,
            daemon=True,
            name="playwright-worker",
        ).start()


def _playwright_worker_loop():
    global _pw_worker_tid
    _pw_worker_tid = threading.get_ident()
    while True:
        fn, args, kwargs, done = _pw_queue.get()
        try:
            done["result"] = fn(*args, **kwargs)
        except Exception as e:
            done["error"] = e
        finally:
            done["event"].set()


def run_playwright(fn, *args, **kwargs):
    """Playwright sync API chỉ chạy trên 1 thread — gọi hàm này từ thread khác."""
    if _pw_worker_tid == threading.get_ident():
        return fn(*args, **kwargs)
    _ensure_playwright_worker()
    done = {"event": threading.Event(), "result": None, "error": None}
    _pw_queue.put((fn, args, kwargs, done))
    done["event"].wait()
    if done["error"] is not None:
        raise done["error"]
    return done["result"]


def _persistent_api():
    return run_playwright(_api_pool.get)


def _reset_persistent_api():
    run_playwright(_api_pool.reset)


def _processing_monitor_state():
    """Đọc từ RAM — poll sau MIN_RENDER_SEC từ submittedAt."""
    now = datetime.now(timezone.utc)
    ad_eligible = []
    xy_eligible = []
    vae_eligible = []
    tool98_eligible = []
    with _processing_cache_lock:
        stale_ids = []
        for oid, doc in _processing_cache.items():
            d = doc.to_dict() or {}
            if d.get("status") != "processing":
                stale_ids.append(oid)
        for oid in stale_ids:
            _processing_cache.pop(oid, None)
        processing_count = len(_processing_cache)
        for doc in _processing_cache.values():
            d = doc.to_dict() or {}
            if d.get("status") != "processing":
                continue
            submitted_at = d.get("submittedAt")
            if submitted_at and (now - submitted_at).total_seconds() <= MIN_RENDER_SEC:
                continue
            rp = _order_render_provider(d)
            if rp == RENDER_PROVIDER_TOOL98:
                if d.get("tool98JobId"):
                    tool98_eligible.append(doc)
            elif rp == RENDER_PROVIDER_XIAOYANG:
                if d.get("xiaoyangTaskId"):
                    xy_eligible.append(doc)
            elif rp == RENDER_PROVIDER_VIDEOAIEASY:
                if d.get("videoaieasyJobId"):
                    vae_eligible.append(doc)
            else:
                job_id = d.get("aidancingJobId")
                if job_id and job_id != "MANUAL":
                    ad_eligible.append(doc)
    return ad_eligible, xy_eligible, vae_eligible, tool98_eligible, processing_count


def on_processing_orders_snapshot(keys, changes, read_time):
    """Listener: chỉ read Firestore khi đơn vào/ra khỏi processing (không poll lặp)."""
    with _processing_cache_lock:
        for ch in changes:
            doc = ch.document
            oid = doc.id
            if ch.type.name == 'REMOVED':
                _processing_cache.pop(oid, None)
                continue
            d = doc.to_dict() or {}
            if d.get('status') == 'processing':
                _processing_cache[oid] = doc
            else:
                _processing_cache.pop(oid, None)


def start_processing_listener():
    db.collection('orders').where(
        filter=FieldFilter("status", "==", "processing")
    ).on_snapshot(on_processing_orders_snapshot)
    print("👂 Listener processing orders — cache RAM, không query Firestore mỗi lần poll")


def _submit_engine_lock():
    """HTTP: submit_lock — poll monitor chạy song song. Browser: browser_lock (Playwright)."""
    return submit_lock if use_api_mode() else browser_lock


def _maybe_refresh_processing_cache():
    """Phòng listener Firestore GOAWAY — đồng bộ lại cache processing định kỳ."""
    global _processing_cache_refresh_at
    if not use_api_mode():
        return
    interval = int(os.environ.get("BOT_PROCESSING_CACHE_REFRESH_SEC", "600"))
    now = time.time()
    if now - _processing_cache_refresh_at < interval:
        return
    _processing_cache_refresh_at = now
    try:
        fresh = {
            doc.id: doc
            for doc in db.collection("orders")
            .where(filter=FieldFilter("status", "==", "processing"))
            .stream()
        }
        with _processing_cache_lock:
            _processing_cache.clear()
            _processing_cache.update(fresh)
        print(f"🔄 Refresh processing cache: {len(fresh)} đơn")
    except Exception as e:
        print(f"⚠️ Refresh processing cache: {e}")


def _monitor_sleep_seconds(eligible_count, processing_count):
    """Không có webhook aidancing — chỉ poll; interval dài khi không có việc."""
    idle = int(os.environ.get("BOT_POLL_IDLE_SEC", "300"))
    wait_render = int(os.environ.get("BOT_POLL_WAIT_RENDER_SEC", "120"))
    active = int(os.environ.get("BOT_POLL_ACTIVE_SEC", "90"))
    if processing_count == 0:
        return idle
    if eligible_count == 0:
        return wait_render
    return active


def _warm_api_session_loop():
    if not use_api_mode():
        return
    _ensure_playwright_worker()
    while True:
        if is_bot_enabled():
            try:
                run_playwright(_api_pool.get)
                print("✅ Tab nền aidancing sẵn sàng — poll qua fetch (không F5 dashboard)")
                return
            except Exception as e:
                print(f"⚠️ Chờ Chrome CDP để khởi tạo session API: {e}")
                try:
                    run_playwright(_api_pool.reset)
                except Exception:
                    pass
        time.sleep(20)

def ensure_cdp_available(cdp_url, timeout=3):
    try:
        url = cdp_url.rstrip("/") + "/json/version"
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False

def _cdp_not_running_error(cdp_url):
    return RuntimeError(
        f"Chrome CDP chưa chạy tại {cdp_url}. "
        "Mở Chrome ở terminal RIÊNG và GIỮ chạy (đừng Ctrl+C), rồi chạy bot:\n"
        "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\\n"
        "    --remote-debugging-port=9222 --remote-allow-origins='*' \\\n"
        "    --user-data-dir=\"$HOME/.chrome-aidancing-motionai\" \\\n"
        "    --profile-directory=\"Profile 4\""
    )

def _ensure_pending_worker():
    global _pending_worker_started
    with _pending_queue_lock:
        if _pending_worker_started:
            return
        _pending_worker_started = True
        threading.Thread(target=_pending_order_worker, daemon=True).start()

def _pending_order_worker():
    while True:
        order_id = None
        with _pending_queue_lock:
            if _pending_order_queue:
                order_id = _pending_order_queue.pop(0)
        if order_id:
            try:
                if xy_motion.enabled_for_bot(BOT_NAME):
                    xy_motion.submit_order(order_id)
                else:
                    submit_order(order_id)
            except Exception as e:
                print(f"❌ Lỗi nạp đơn {order_id}: {e}")
                _session_error_backoff[order_id] = time.time() + SESSION_ERROR_BACKOFF_SEC
        else:
            time.sleep(0.5)

AIDANCING_BLOCKED_MARKERS = (
    "bảo trì", "bao tri", "maintenance", "under maintenance",
    "scheduled maintenance", "hệ thống đang", "temporarily unavailable",
    "service unavailable", "coming soon",
)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {}, loadTimes: function() {}, csi: function() {} };
Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
  parameters.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : originalQuery(parameters);
"""

class AidancingBrowserSession:
    """Wrapper: CDP mode không đóng Chrome của user khi bot xong."""

    def __init__(self, context, close_context_on_exit=True):
        self.context = context
        self.close_context_on_exit = close_context_on_exit
        self._pages = []

    def new_page(self):
        page = self.context.new_page()
        self._pages.append(page)
        return page

    def cookies(self, urls=None):
        if urls:
            return self.context.cookies(urls)
        return self.context.cookies()

    def clear_cookies(self):
        self.context.clear_cookies()

    def close(self):
        for page in self._pages:
            try:
                page.close()
            except Exception:
                pass
        self._pages.clear()
        if self.close_context_on_exit:
            try:
                self.context.close()
            except Exception:
                pass

def close_extra_aidancing_tabs(session, keep_page):
    """Đóng tab aidancing phụ (do nút Tải mở target=_blank)."""
    for p in list(session.context.pages):
        if p == keep_page:
            continue
        try:
            u = p.url or ''
            if 'aidancing' in u or u.startswith('blob:') or 'proxy/files' in u:
                p.close()
        except Exception:
            pass

def _apply_stealth(context):
    try:
        context.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception as e:
        print(f"⚠️ Không gắn stealth script: {e}")

def _aidancing_chrome_args():
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if os.environ.get("BOT_CHROME_OFFSCREEN", "0") == "1":
        args.append("--window-position=-2400,-2400")
    return args

def _chrome_profile_dir():
    return os.path.abspath(os.environ.get("BOT_CHROME_PROFILE", BOT_CHROME_PROFILE))

def launch_aidancing_browser(playwright):
    cdp_url = os.environ.get("BOT_CDP_URL", "").strip()
    if cdp_url:
        if not ensure_cdp_available(cdp_url):
            raise _cdp_not_running_error(cdp_url)
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            viewport={"width": 1280, "height": 800},
        )
        _apply_stealth(context)
        print(f"🔗 Nối Chrome qua CDP ({cdp_url}) — dùng Chrome thật, không đóng khi bot xong.")
        return AidancingBrowserSession(context, close_context_on_exit=False)

    profile_dir = _chrome_profile_dir()
    kwargs = dict(
        user_data_dir=profile_dir,
        headless=False,
        slow_mo=int(os.environ.get("BOT_SLOW_MO", "500")),
        ignore_default_args=["--enable-automation"],
        args=_aidancing_chrome_args(),
        viewport={"width": 1280, "height": 800},
        locale="vi-VN",
        timezone_id="Asia/Ho_Chi_Minh",
    )
    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception as e:
        print(f"⚠️ Không mở được Chrome ({e}), dùng Chromium bundled...")
        context = playwright.chromium.launch_persistent_context(**kwargs)
    _apply_stealth(context)
    return AidancingBrowserSession(context, close_context_on_exit=True)

def _aidancing_page_info(page):
    try:
        return f"{page.url} | {page.title()}"
    except Exception:
        return page.url

def is_aidancing_blocked(page):
    try:
        url = (page.url or "").lower()
        if any(x in url for x in ("maintenance", "maintain", "bao-tri")):
            return True
        combined = f"{page.title() or ''} {page.content()}".lower()
        return any(marker in combined for marker in AIDANCING_BLOCKED_MARKERS)
    except Exception:
        return False

def _raise_if_aidancing_blocked(page):
    if not is_aidancing_blocked(page):
        return
    print(f"🚫 Aidancing chặn/trang bảo trì: {_aidancing_page_info(page)}")
    raise RuntimeError(
        "Aidancing hiển thị trang bảo trì hoặc chặn trình duyệt tự động. "
        "Thường do profile Chrome BOT chưa có cookie đăng nhập (Chrome thường của bạn vẫn vào được vì đã login). "
        "Cách xử lý: thoát hết Chrome (Cmd+Q), copy profile Default đã login sang ~/.chrome-aidancing-bot "
        "(xem README hoặc hướng dẫn setup), mở Chrome CDP rồi BOT_CDP_URL=http://127.0.0.1:9222 python3 bot.py --name mac --mode api"
    )

def _aidancing_on_dashboard(page):
    u = page.url.lower()
    if "login" in u or "signin" in u or "sign-in" in u:
        return False
    if is_aidancing_blocked(page):
        return False
    return "dashboard" in u

def goto_aidancing_dashboard(page, session, login_wait_sec=120):
    """Mở dashboard; xử lý redirect loop (cookie hỏng) và chờ đăng nhập thủ công."""

    def _goto(url):
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        print(f"📄 {_aidancing_page_info(page)}")
        _raise_if_aidancing_blocked(page)

    try:
        _goto(DASHBOARD_URL)
    except Exception as e:
        err = str(e)
        if "Aidancing hiển thị" in err:
            raise
        if "ERR_TOO_MANY_REDIRECTS" in err or "too many redirects" in err.lower():
            print("⚠️ Redirect loop — xóa cookie profile bot và thử lại...")
            try:
                session.clear_cookies()
            except Exception as ce:
                print(f"   (không xóa được cookie: {ce})")
            _goto(AIDANCING_ORIGIN)
            page.wait_for_timeout(2000)
            _goto(DASHBOARD_URL)
        else:
            raise

    page.wait_for_timeout(2000)
    if _aidancing_on_dashboard(page):
        return

    print(f"⚠️ Chưa vào Dashboard (URL: {page.url})")
    print("👉 Đăng nhập aidancing.net trên cửa sổ Chrome BOT (thư mục bot_chrome_profile).")
    print("   Chrome thường của bạn dùng profile khác — cần login 1 lần trên cửa sổ bot.")

    deadline = time.time() + login_wait_sec
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if _aidancing_on_dashboard(page):
            print("✅ Đã vào Dashboard sau khi đăng nhập.")
            return
        try:
            _goto(DASHBOARD_URL)
        except Exception as e:
            if "Aidancing hiển thị" in str(e):
                raise

    raise RuntimeError(
        f"Không vào được Dashboard sau {login_wait_sec}s. "
        f"Đăng nhập trên cửa sổ Chrome bot rồi chạy lại. URL: {page.url}"
    )

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8783657660:AAHRfxHNiohZzPJ2OaQ7TEMNKwb7AAlp2uo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6067707939")
AIDANCING_LOW_BALANCE_THRESHOLD = 10

def normalize_bot_name(name):
    name = (name or '').strip().lower()
    name = re.sub(r'[^a-z0-9_-]', '-', name)
    name = re.sub(r'-+', '-', name).strip('-')
    return name[:64]

def ensure_bot_registered():
    ref = db.collection('bots').document(BOT_NAME)
    doc = ref.get()
    now = firestore.SERVER_TIMESTAMP
    if not doc.exists:
        ref.set({
            'name': BOT_NAME,
            'displayName': BOT_NAME,
            'enabled': False,
            'hostname': socket.gethostname(),
            'createdAt': now,
            'startedAt': now,
        })
        print(f"🆕 Bot mới đăng ký trên Firestore: {BOT_NAME} (mặc định TẮT — bật trên Admin)")
    else:
        ref.set({
            'name': BOT_NAME,
            'startedAt': now,
            'hostname': socket.gethostname(),
        }, merge=True)

def on_bot_config_snapshot(keys, changes, read_time):
    # Document watch callback: (sorted_keys, DocumentChange[], read_time) — not a DocumentSnapshot.
    if not changes:
        return
    enabled = False
    data = {}
    for change in changes:
        doc = change.document
        if getattr(doc, 'exists', False):
            data = doc.to_dict() or {}
            enabled = bool(data.get('enabled', False))
        break
    prev = is_bot_enabled()
    set_bot_enabled(enabled)
    if enabled != prev:
        status = "🟢 BẬT — bot đang xử lý đơn" if enabled else "🔴 TẮT — bot không làm gì"
        print(f"\n[{BOT_NAME}] Admin đổi trạng thái: {status}\n")
    if data:
        if xy_motion.enabled_for_bot(BOT_NAME):
            xy_motion.apply_render_provider_from_bot_data(data, source="admin")
        else:
            _apply_render_provider(_render_provider_from_bot_data(data), source="admin")

def start_bot_control_listener():
    ensure_bot_registered()
    doc = db.collection('bots').document(BOT_NAME).get()
    set_bot_enabled(bool(doc.to_dict().get('enabled', False)) if doc.exists else False)
    status = "🟢 BẬT" if is_bot_enabled() else "🔴 TẮT"
    print(f"[{BOT_NAME}] Trạng thái hiện tại: {status}")
    if not is_bot_enabled():
        print("⏸️  Bot đang TẮT. Vào Admin → Bots để bật.")

    db.collection('bots').document(BOT_NAME).on_snapshot(on_bot_config_snapshot)

def send_telegram_message(text):
    try:
        if "[Kaling]" not in text:
            text = f"[Kaling] {text}"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if res.status_code != 200:
            print(f"❌ Lỗi gửi tin nhắn Telegram: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối gửi Telegram: {e}")

_INTERNAL_ERROR_MARKERS = (
    'aidancing', 'xiaoyang', 'xiao yang', '/api/proxy/', 'proxy/jobs', 'proxy/files',
    '401', '503', '502', '429', '400', '504', 'đăng nhập lại', 'bảo trì',
    'chrome cdp', 'connect_over_cdp', 'econnrefused', 'target closed',
    'different thread', 'job id', 'dashboard', 'create/general',
    'bot nạp', 'maintenance', 'option_key', 'modal_key', 'direct_media',
    'workers', 'e_direct_media', 'session expired',
)
_ERROR_TELEGRAM_COOLDOWN = 900
_error_telegram_sent = {}
_error_telegram_lock = threading.Lock()
_session_error_backoff = {}
SESSION_ERROR_BACKOFF_SEC = 300

def is_internal_bot_error(err):
    s = (err or '').lower()
    return any(m in s for m in _INTERNAL_ERROR_MARKERS)

def notify_internal_error_telegram(order_id, order_data, err, context=''):
    now = time.time()
    with _error_telegram_lock:
        last = _error_telegram_sent.get(order_id, 0)
        if now - last < _ERROR_TELEGRAM_COOLDOWN:
            return
        _error_telegram_sent[order_id] = now
    short_id = order_id[-6:].upper()
    user_name = (order_data or {}).get('userName', 'Khách hàng')
    user_email = (order_data or {}).get('userEmail', 'N/A')
    ctx = f" ({context})" if context else ""
    err_text = (err or '')[:500]
    msg = (
        f"🚨 <b>[Kaling] BOT LỖI NỘI BỘ{ctx}</b>\n\n"
        f"🆔 Mã đơn: #{short_id}\n"
        f"👤 Khách: {user_name}\n"
        f"📧 Email: {user_email}\n"
        f"⚠️ Chi tiết:\n<code>{err_text}</code>"
    )
    send_telegram_message(msg)

def apply_bot_error_update(doc_ref, order_id, order_data, err, context='nạp đơn'):
    """Lỗi Aidancing/hạ tầng bot → Telegram admin, không hiện adminNote cho khách."""
    if is_internal_bot_error(err):
        notify_internal_error_telegram(order_id, order_data, err, context)
        _session_error_backoff[order_id] = time.time() + SESSION_ERROR_BACKOFF_SEC
        return True
    doc_ref.update({
        'adminNote': f"Bot nạp lỗi: {err}",
        'updatedAt': firestore.SERVER_TIMESTAMP,
    })
    return False

def _pending_submit_backoff_active(order_id):
    return time.time() < _session_error_backoff.get(order_id, 0)

def scrape_aidancing_balance(page):
    """Đọc số coin còn lại trên header aidancing.net (vd: 101.0)."""
    try:
        val = page.evaluate('''() => {
            const pick = (s) => {
                const m = String(s).trim().match(/^(\\d+(?:\\.\\d+)?)$/);
                return m ? parseFloat(m[1]) : null;
            };
            const scopes = document.querySelectorAll('header *, nav *, [class*="wallet"], [class*="balance"], [class*="coin"]');
            for (const el of scopes) {
                if (el.children.length > 0) continue;
                const v = pick(el.textContent);
                if (v !== null && v >= 0 && v < 100000) return v;
            }
            return null;
        }''')
        if val is not None:
            return float(val)
    except Exception as e:
        print(f"⚠️ Không đọc được balance aidancing: {e}")
    return None

def alert_low_aidancing_balance(balance, extra=''):
    if balance is None or balance >= AIDANCING_LOW_BALANCE_THRESHOLD:
        return
    msg = (
        f"🚨🚨 <b>CẢNH BÁO KHẨN — SẮP HẾT COIN AIDANCING!</b>\n\n"
        f"💰 Số dư aidancing.net: <b>{balance}</b> Coin\n"
        f"⚠️ Dưới ngưỡng {AIDANCING_LOW_BALANCE_THRESHOLD} Coin — "
        f"<b>nạp gấp</b> trước khi bot không tạo được đơn!\n"
        f"{extra}"
    )
    send_telegram_message(msg)

def download_file(url, filename, cookies=None, referer=None, retries=2):
    print(f"📥 Tải file (requests): {filename}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': referer or f'{AIDANCING_ORIGIN}/dashboard',
        'Origin': AIDANCING_ORIGIN,
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, cookies=cookies, timeout=120)
            if response.status_code in (503, 502, 429) and attempt < retries:
                wait = 5 * attempt
                print(f"⚠️ HTTP {response.status_code} — thử lại {attempt}/{retries} sau {wait}s...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            with open(filename, 'wb') as f:
                f.write(response.content)
            return os.path.abspath(filename)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(3 * attempt)
    print(f"❌ Lỗi tải file: {last_err}")
    return None

def download_aidancing_result(session, page, url, filename, download_locator=None):
    """Tải video kết quả aidancing — không click mở tab (aidancing dùng target=_blank)."""
    print(f"📥 Tải kết quả aidancing: {filename}...")
    if not url.startswith('http'):
        url = AIDANCING_ORIGIN + url

    def save_bytes(data):
        with open(filename, 'wb') as f:
            f.write(data)
        return os.path.abspath(filename)

    def session_get(target_url, label):
        try:
            resp = session.context.request.get(
                target_url,
                headers={'Referer': DASHBOARD_URL, 'Origin': AIDANCING_ORIGIN},
                timeout=120000,
            )
            if resp.ok:
                save_bytes(resp.body())
                print(f"✅ {label}")
                return os.path.abspath(filename)
            print(f"⚠️ {label} — HTTP {resp.status}")
        except Exception as e:
            print(f"⚠️ {label} — {e}")
        return None

    # 1) Tải thẳng URL proxy/API — không click (tránh mở tab mới)
    result = session_get(url, "Tải direct URL (session cookie)")
    if result:
        return result

    # 2) fetch() ngay trên dashboard (credentials: include)
    try:
        data = page.evaluate('''async (videoUrl) => {
            const r = await fetch(videoUrl, { credentials: 'include' });
            if (!r.ok) return { ok: false, status: r.status };
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let binary = '';
            const chunk = 0x8000;
            for (let i = 0; i < bytes.length; i += chunk) {
                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
            }
            return { ok: true, b64: btoa(binary) };
        }''', url)
        if data and data.get('ok') and data.get('b64'):
            save_bytes(base64.b64decode(data['b64']))
            print("✅ Tải qua fetch in-page")
            return os.path.abspath(filename)
        if data:
            print(f"⚠️ In-page fetch HTTP {data.get('status')}")
    except Exception as e:
        print(f"⚠️ In-page fetch lỗi: {e}")

    # 3) Nút Tải mở tab video mới (target=_blank) — bắt tab, lấy src, đóng tab
    if download_locator is not None and download_locator.count() > 0:
        new_page = None
        try:
            print("🖱️ Nút Tải mở tab mới — bắt tab video...")
            with session.context.expect_page(timeout=30000) as page_info:
                download_locator.click()
            new_page = page_info.value
            new_page.wait_for_load_state('domcontentloaded', timeout=30000)
            new_page.wait_for_timeout(1500)
            video_url = new_page.evaluate('''() => {
                const v = document.querySelector('video');
                if (v) {
                    const s = v.querySelector('source');
                    const src = (s && s.src) || v.src || v.currentSrc || '';
                    if (src) return src;
                }
                return location.href;
            }''')
            if video_url and not video_url.startswith('http'):
                video_url = AIDANCING_ORIGIN + video_url
            if video_url:
                print(f"🔗 URL tab video: {video_url[:100]}...")
                result = session_get(video_url, "Tải từ tab video")
                if result:
                    return result
                result = session_get(url, "Tải lại URL gốc sau tab")
                if result:
                    return result
        except Exception as e:
            print(f"⚠️ Xử lý tab video: {e}")
        finally:
            if new_page:
                try:
                    new_page.close()
                except Exception:
                    pass
            close_extra_aidancing_tabs(session, page)

    # 4) Fallback requests + cookie
    try:
        cookie_list = session.cookies(urls=[AIDANCING_ORIGIN, f"{AIDANCING_ORIGIN}/"])
        jar = {c['name']: c['value'] for c in cookie_list}
    except Exception:
        jar = {c['name']: c['value'] for c in session.cookies()}
    return download_file(url, filename, cookies=jar, referer=DASHBOARD_URL, retries=3)

def upload_to_r2(file_path, folder="results"):
    try:
        return upload_result_file(file_path, folder=folder)
    except DirectMediaError as e:
        print(f"❌ Lỗi R2: {e}")
    except Exception as e:
        print(f"❌ Lỗi R2: {e}")
    return None

def send_completion_email(order_id, order_data, result_link):
    user_email = order_data.get('userEmail')
    user_name = order_data.get('userName', 'Khách hàng')
    service_type = order_data.get('serviceType', 'copy-motion-photo')
    
    if not user_email:
        print("⚠️ Không tìm thấy Email của khách để gửi thông báo hoàn thành đơn.")
        return
        
    print(f"📧 Đang gửi email thông báo hoàn thành đơn tới: {user_email}...")
    
    # Ánh xạ tên dịch vụ tiếng Việt
    service_label = service_type
    if service_type == 'copy-motion-photo':
        service_label = "AI Copy Chuyển Động Vào Ảnh (30s)"
    elif service_type == 'copy-motion-multi':
        service_label = "AI Copy Nhảy Nhiều Người"
    elif service_type == 'char-to-video-fashion':
        service_label = "AI Copy Thời Trang"
    elif service_type == 'char-to-video-ads':
        service_label = "AI Copy Sản Phẩm"

    short_order_id = order_id[-6:].upper()
    
    payload = {
        "service_id": "service_6r6rd2q",
        "template_id": "template_09eir3r",
        "user_id": "92pP97oTzMGR4p_Zp",
        "template_params": {
            "user_name": user_name,
            "user_email": user_email,
            "order_id": short_order_id,
            "result_link": result_link,
            "service_label": service_label
        }
    }
    
    try:
        url = "https://api.emailjs.com/api/v1.0/email/send"
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        if response.status_code == 200 or response.text == "OK":
            print(f"✅ Gửi email thông báo qua EmailJS thành công!")
        else:
            print(f"❌ Lỗi gửi email qua EmailJS: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Lỗi kết nối khi gửi email thông báo qua EmailJS: {e}")

def use_api_mode():
    """Pure HTTP — AIDANCING_COOKIE + XiaoYang API, không cần Chrome/CDP."""
    mode = os.environ.get("BOT_MODE", "browser").strip().lower()
    return mode in ("api", "http")

def _complete_order_with_video(doc, local_vid):
    """Upload R2 + cập nhật Firestore + thông báo."""
    r2_url = upload_to_r2(local_vid)
    if not r2_url:
        return False
    db.collection('orders').document(doc.id).update({
        'status': 'completed',
        'resultLink': r2_url,
        'updatedAt': firestore.SERVER_TIMESTAMP
    })
    print(f"✅ ĐÃ TRẢ HÀNG CHO ĐƠN {doc.id}")
    try:
        order_data = doc.to_dict()
        short_id = doc.id[-6:].upper()
        user_name = order_data.get('userName', 'Khách hàng')
        user_email = order_data.get('userEmail', 'N/A')
        char_img = order_data.get('characterImageLink', '')
        msg = (
            f"✅ <b>ĐƠN HÀNG HOÀN THÀNH</b>\n\n"
            f"🆔 Mã đơn: #{short_id}\n"
            f"👤 Khách: {user_name}\n"
            f"📧 Email: {user_email}\n"
        )
        if char_img:
            msg += f"📸 Ảnh đầu vào: <a href=\"{char_img}\">Xem ảnh gốc</a>\n"
        msg += f"📹 Kết quả: <a href=\"{r2_url}\">Xem video kết quả</a>"
        send_telegram_message(msg)
    except Exception as tele_err:
        print(f"⚠️ Lỗi gửi thông báo Telegram hoàn thành: {tele_err}")
    try:
        send_completion_email(doc.id, doc.to_dict(), r2_url)
    except Exception as mail_err:
        print(f"⚠️ Không gửi được email thông báo: {mail_err}")
    if os.path.exists(local_vid):
        os.remove(local_vid)
    _pop_processing_cache(doc.id)
    return True

def check_finished_orders_api():
    """Monitor Aidancing + XiaoYang + VideoAiEasy — Pure HTTP (không giữ browser_lock)."""
    if not is_bot_enabled():
        return
    _maybe_refresh_processing_cache()
    ad_orders, xy_orders, vae_orders, tool98_orders, _ = _processing_monitor_state()
    if not ad_orders and not xy_orders and not vae_orders and not tool98_orders:
        return

    print(
        f"\n🔍 [MONITOR/HTTP] Poll Aidancing={len(ad_orders)} XiaoYang={len(xy_orders)} "
        f"VideoAiEasy={len(vae_orders)} Tool98={len(tool98_orders)} "
        f"(sau {MIN_RENDER_SEC // 60}p từ submittedAt)..."
    )
    if ad_orders:
        try:
            _http_poll_orders(ad_orders)
        except SessionExpiredError as e:
            print(f"❌ Session hết hạn: {e}")
            _reset_http_client()
        except Exception as e:
            err = str(e)
            print(f"❌ Lỗi monitor Aidancing HTTP: {e}")
            if any(x in err.lower() for x in ("401", "403", "session expired", "aidancing_cookie")):
                _reset_http_client()
    if xy_orders:
        try:
            if xy_motion.enabled_for_bot(BOT_NAME):
                xy_motion.poll_xiaoyang_orders(xy_orders)
            else:
                _http_poll_xiaoyang_orders(xy_orders)
        except Exception as e:
            print(f"❌ Lỗi monitor XiaoYang: {e}")
    if vae_orders and xy_motion.enabled_for_bot(BOT_NAME):
        try:
            xy_motion.poll_videoaieasy_orders(vae_orders)
        except Exception as e:
            print(f"❌ Lỗi monitor VideoAiEasy: {e}")
    if tool98_orders and xy_motion.enabled_for_bot(BOT_NAME):
        try:
            xy_motion.poll_tool98_orders(tool98_orders)
        except Exception as e:
            print(f"❌ Lỗi monitor Tool98: {e}")

def _mark_order_processing(
    doc_ref,
    job_id,
    *,
    provider=RENDER_PROVIDER_AIDANCING,
    xiaoyang_key_index=None,
):
    """Chỉ chuyển processing sau khi engine render đã nhận job."""
    payload = {
        'status': 'processing',
        'renderProvider': provider,
        'submittedAt': firestore.SERVER_TIMESTAMP,
        'updatedAt': firestore.SERVER_TIMESTAMP,
    }
    if provider == RENDER_PROVIDER_XIAOYANG:
        payload['xiaoyangTaskId'] = str(job_id)
        if xiaoyang_key_index is not None:
            payload['xiaoyangKeyIndex'] = int(xiaoyang_key_index)
    else:
        payload['aidancingJobId'] = str(job_id)
    doc_ref.update(payload)


def submit_order(order_id):
    provider = get_active_render_provider()
    if provider == RENDER_PROVIDER_XIAOYANG:
        submit_to_xiaoyang(order_id)
    else:
        submit_to_aidancing(order_id)


def submit_to_xiaoyang(order_id):
    if not is_bot_enabled():
        print(f"⏸️ [{BOT_NAME}] Bot TẮT — bỏ qua nạp đơn {order_id}")
        return
    if _pending_submit_backoff_active(order_id):
        return
    with _submitting_orders_lock:
        if order_id in _submitting_orders:
            print(f"⏭️ [{BOT_NAME}] Đơn {order_id} đang nạp — bỏ qua trùng lặp")
            return
        _submitting_orders.add(order_id)
    try:
        with _submit_engine_lock():
            doc_ref = db.collection("orders").document(order_id)
            doc = doc_ref.get()
            if not doc.exists:
                return
            data = doc.to_dict() or {}
            if data.get("status") != "pending":
                return

            print(f"\n⚡ [NẠP ĐƠN / XiaoYang] {order_id}...")
            img_url = (data.get("characterImageLink") or "").strip()
            vid_url = (data.get("referenceVideoLink") or "").strip()
            if not img_url or not vid_url:
                print(f"❌ Thiếu link ảnh/video cho đơn {order_id}")
                _fail_order_processing(
                    doc,
                    data,
                    "Thiếu characterImageLink hoặc referenceVideoLink",
                    USER_NOTE_FILES_MISSING,
                    "submit xiaoyang",
                )
                return

            try:
                key_idx = _pick_xiaoyang_key_index(data)
                api = _get_xy_client(key_idx)
                modal, option = _xiaoyang_modal_for_order(data)
                prompt = (data.get("prompt") or get_env(
                    "XIAOYANG_PROMPT", "Follow the reference motion naturally"
                )).strip()
                from xiaoyang_direct import direct_worker_base

                dw = direct_worker_base()
                if dw:
                    print(f"📎 Direct worker: {dw}")
                tier = "Turbo/v3.0" if modal == XIAOYANG_MODAL_TURBO else "Thường/v2.6"
                print(
                    f"🚀 [XiaoYang HTTP] {tier} — modelId={data.get('modelId')} "
                    f"→ motion {modal}/{option}..."
                )
                resp = api.create_task(
                    modal,
                    option,
                    prompt,
                    image_url=img_url,
                    video_url=vid_url,
                    motion_orientation=get_env("XIAOYANG_MOTION_ORIENTATION", "video"),
                )
                task_id = resp.get("task_id")
                if not task_id:
                    raise XiaoyangApiError(f"Không có task_id: {resp}")
                print(f"🆔 [XiaoYang] key#{key_idx} task: {task_id} ({resp.get('status')})")
                _mark_order_processing(
                    doc_ref,
                    task_id,
                    provider=RENDER_PROVIDER_XIAOYANG,
                    xiaoyang_key_index=key_idx,
                )
                _session_error_backoff.pop(order_id, None)
                print(f"✅ Đơn {order_id} → processing (XiaoYang)")
                try:
                    short_id = order_id[-6:].upper()
                    send_telegram_message(
                        f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b> (XiaoYang)\n\n"
                        f"🆔 Mã đơn: #{short_id}\n"
                        f"👤 Nick XY: {_xy_account_label(key_idx)}\n"
                        f"🤖 Task: <code>{task_id}</code>\n"
                        f"⏳ Poll sau {MIN_RENDER_SEC // 60} phút..."
                    )
                except Exception:
                    pass
            except (XiaoyangAuthError, XiaoyangApiError, DirectMediaError, MediaValidationError, ValueError) as e:
                print(f"❌ Nạp XiaoYang thất bại {order_id}: {e}")
                _session_error_backoff[order_id] = time.time() + SESSION_ERROR_BACKOFF_SEC
                if isinstance(e, XiaoyangAuthError):
                    try:
                        _invalidate_xy_key(key_idx)
                    except NameError:
                        pass
                if isinstance(e, MediaValidationError):
                    user_note = user_note_for_media_validation(str(e))
                else:
                    user_note = USER_NOTE_SUBMIT_FAILED
                _fail_order_processing(doc, data, str(e), user_note, "submit xiaoyang")
    finally:
        with _submitting_orders_lock:
            _submitting_orders.discard(order_id)


def submit_to_aidancing(order_id, fallback_reason=None):
    if not is_bot_enabled():
        print(f"⏸️ [{BOT_NAME}] Bot TẮT — bỏ qua nạp đơn {order_id}")
        return
    if _pending_submit_backoff_active(order_id):
        return
    with _submitting_orders_lock:
        if order_id in _submitting_orders:
            print(f"⏭️ [{BOT_NAME}] Đơn {order_id} đang nạp — bỏ qua trùng lặp")
            return
        _submitting_orders.add(order_id)
    try:
        with _submit_engine_lock():
            doc_ref = db.collection('orders').document(order_id)
            doc = doc_ref.get()
            if not doc.exists:
                return
            data = doc.to_dict()
            if data.get('status') != 'pending':
                return

            fb = f" [fallback: {fallback_reason}]" if fallback_reason else ""
            print(f"\n⚡ [NẠP ĐƠN / Aidancing]{fb} {order_id}... (giữ pending cho đến khi aidancing OK)")

            char_path = None
            vid_path = None

            # Thử tải tối đa 2 lần
            for attempt in range(1, 3):
                if attempt > 1: print(f"🔄 Thử lại lần {attempt}...")
                char_path = download_file(data.get('characterImageLink'), f"char_{order_id}.png")
                vid_path = download_file(data.get('referenceVideoLink'), f"vid_{order_id}.mp4")

                if char_path and vid_path:
                    break
                time.sleep(2)

            if not char_path or not vid_path:
                print(f"❌ Không thể tải file sau 2 lần thử cho đơn {order_id}")
                # Hoàn tiền cho khách
                cost_coins = data.get('costCoins', 0)
                user_id = data.get('userId')
                if cost_coins > 0 and user_id:
                    try:
                        db.collection('users').document(user_id).update({
                            'coins': firestore.Increment(cost_coins)
                        })
                        print(f"💰 Đã hoàn lại {cost_coins} coin cho user {user_id}")
                    except Exception as e:
                        print(f"⚠️ Lỗi khi hoàn tiền cho user {user_id}: {e}")

                doc_ref.update({
                    'status': 'failed',
                    'adminNote': firestore.DELETE_FIELD,
                    'systemNote': USER_NOTE_FILES_MISSING,
                    'updatedAt': firestore.SERVER_TIMESTAMP
                })

                # Gửi thông báo Telegram: Đơn hàng thất bại
                try:
                    short_id = order_id[-6:].upper()
                    user_name = data.get('userName', 'Khách hàng')
                    user_email = data.get('userEmail', 'N/A')
                    msg = (
                        f"❌ <b>ĐƠN HÀNG THẤT BẠI</b>\n\n"
                        f"🆔 Mã đơn: #{short_id}\n"
                        f"👤 Khách: {user_name}\n"
                        f"📧 Email: {user_email}\n"
                        f"📝 Lý do: Không thể tải ảnh/video nhân vật quý khách tải lên."
                    )
                    send_telegram_message(msg)
                except Exception as tele_err:
                    print(f"⚠️ Lỗi gửi thông báo Telegram thất bại: {tele_err}")
                if char_path and os.path.exists(char_path): os.remove(char_path)
                if vid_path and os.path.exists(vid_path): os.remove(vid_path)
                return

            if use_api_mode():
                try:
                    model_id = data.get('modelId', '124')
                    print(f"🚀 [HTTP] Nạp đơn model {model_id}...")
                    job_id = _http_create_job(model_id, char_path, vid_path)
                    print(f"🆔 [HTTP] Job mới: {job_id}")
                    _mark_order_processing(doc_ref, job_id, provider=RENDER_PROVIDER_AIDANCING)
                    _session_error_backoff.pop(order_id, None)
                    print(f"✅ Đơn {order_id} → processing (aidancing đã nhận job)")
                    try:
                        short_id = order_id[-6:].upper()
                        send_telegram_message(
                            f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b>\n\n"
                            f"🆔 Mã đơn: #{short_id}\n"
                            f"🤖 Job ID aidancing: <code>{job_id}</code>\n"
                            f"⏳ Đang render (HTTP mode)..."
                        )
                    except Exception:
                        pass
                except SessionExpiredError as e:
                    print(f"❌ Session hết hạn: {e}")
                    _reset_http_client()
                    apply_bot_error_update(doc_ref, order_id, data, str(e), 'nạp HTTP')
                except Exception as e:
                    print(f"❌ Lỗi nạp HTTP: {e}")
                    err = str(e)
                    if any(x in err.lower() for x in ('401', '403', 'session expired', 'aidancing_cookie')):
                        _reset_http_client()
                    apply_bot_error_update(doc_ref, order_id, data, err, 'nạp HTTP')
                finally:
                    if char_path and os.path.exists(char_path):
                        os.remove(char_path)
                    if vid_path and os.path.exists(vid_path):
                        os.remove(vid_path)
                return

            def _pw_browser_submit():
                with sync_playwright() as p:
                    browser = launch_aidancing_browser(p)
                    page = browser.new_page()
                    try:
                        print("🌐 Đang kiểm tra danh sách Job cũ trên Dashboard...")
                        goto_aidancing_dashboard(page, browser)
                        balance = scrape_aidancing_balance(page)
                        if balance is not None:
                            print(f"💰 Aidancing balance: {balance} Coin")
                        if balance is not None and balance < AIDANCING_LOW_BALANCE_THRESHOLD:
                            short_id = order_id[-6:].upper()
                            user_name = data.get('userName', 'Khách hàng')
                            alert_low_aidancing_balance(
                                balance,
                                extra=f"\n📋 Bot đang nạp đơn: #{short_id}\n👤 Khách: {user_name}"
                            )
                        old_job_ids = set(re.findall(r'\b\d{6}\b', page.content()))
                        print(f"📦 Đã ghi nhận {len(old_job_ids)} Job ID cũ.")
                        model_id = data.get('modelId', '124')
                        create_url = f"{AIDANCING_ORIGIN}/create/general?id={model_id}"
                        print(f"🌐 Vào trang tạo: {create_url}")
                        page.goto(create_url, timeout=90000)
                        page.set_input_files('input[name="image"]', char_path)
                        page.set_input_files('input[name="video"]', vid_path)
                        page.locator('button.neon-ai-2').first.click()
                        print("⏳ Đợi chuyển về Dashboard và quét Job ID mới...")
                        page.wait_for_url("**/dashboard**", timeout=60000)
                        job_id = None
                        for _ in range(15):
                            page.wait_for_timeout(2000)
                            current_job_ids = set(re.findall(r'\b\d{6}\b', page.content()))
                            new_jobs = current_job_ids - old_job_ids
                            if new_jobs:
                                job_id = sorted(list(new_jobs))[-1]
                                break
                        if not job_id:
                            print("⚠️ Không tìm thấy Job ID mới sau 30s! Dùng cách lấy mặc định...")
                            job_ids = re.findall(r'\b\d{6}\b', page.content())
                            if job_ids:
                                job_id = job_ids[0]
                                print(f"🆔 LẤY ĐƯỢC JOB ID (Fallback): {job_id}")
                        return job_id
                    finally:
                        browser.close()

            try:
                job_id = run_playwright(_pw_browser_submit)
                if job_id:
                    print(f"🆔 LẤY ĐƯỢC JOB ID MỚI: {job_id}")
                    _mark_order_processing(doc_ref, job_id)
                    _session_error_backoff.pop(order_id, None)
                    print(f"✅ Đơn {order_id} → processing (aidancing đã nhận job)")
                    try:
                        short_id = order_id[-6:].upper()
                        user_name = data.get('userName', 'Khách hàng')
                        user_email = data.get('userEmail', 'N/A')
                        msg = (
                            f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b>\n\n"
                            f"🆔 Mã đơn: #{short_id}\n"
                            f"👤 Khách: {user_name}\n"
                            f"📧 Email: {user_email}\n"
                            f"🤖 Job ID aidancing: <code>{job_id}</code>\n"
                            f"⏳ Đang render trên aidancing.net..."
                        )
                        send_telegram_message(msg)
                    except Exception as tele_err:
                        print(f"⚠️ Lỗi gửi thông báo Telegram xử lý: {tele_err}")
                else:
                    err = 'Bot nạp xong nhưng không lấy được Job ID aidancing — vẫn pending, thử lại sau.'
                    apply_bot_error_update(doc_ref, order_id, data, err, 'nạp browser')
            except Exception as e:
                print(f"❌ Lỗi nạp: {e}")
                apply_bot_error_update(doc_ref, order_id, data, str(e), 'nạp browser')
            finally:
                if os.path.exists(char_path):
                    os.remove(char_path)
                if os.path.exists(vid_path):
                    os.remove(vid_path)
    finally:
        with _submitting_orders_lock:
            _submitting_orders.discard(order_id)

# --- PHA 2: RÌNH KẾT QUẢ ---
def check_finished_orders():
    if use_api_mode():
        try:
            check_finished_orders_api()
        except Exception as e:
            print(f"❌ Lỗi monitor API: {e}")
        return
    if not is_bot_enabled():
        return
    try:
        # Nếu đang nạp đơn thì không check dashboard để tránh khóa profile
        if browser_lock.locked():
            return

        ad_orders, _, _, _, _ = _processing_monitor_state()
        if not ad_orders:
            return

        orders_to_check = ad_orders
        print(f"\n🔍 [MONITOR] Đang rình kết quả Aidancing cho {len(orders_to_check)} đơn đủ {MIN_RENDER_SEC // 60}p...")
        with browser_lock:
            with sync_playwright() as p:
                browser = launch_aidancing_browser(p)
                page = browser.new_page()
                try:
                    goto_aidancing_dashboard(page, browser)
                except RuntimeError as e:
                    print(f"⚠️ {e}")
                    time.sleep(60)
                    browser.close()
                    return
                print(f"🌐 Đang ở: {page.url}")
                time.sleep(10)

                for doc in orders_to_check:
                    job_id = str(doc.to_dict().get('aidancingJobId'))
                    print(f"🧐 Đang tìm Job {job_id}...")

                    # Thử tìm text trong toàn bộ trang
                    if job_id not in page.content():
                        print(f"❌ Không thấy mã {job_id} trên trang này. Kiểm tra xem Job có ở trang 2 không?")
                        continue

                    # [FIX]: Tìm chính xác thẻ Card chứa đơn hàng này bằng cách mở rộng dần từ phần tử nhỏ nhất
                    # Đảm bảo không bao giờ bị dính vào thẻ List to đùng chứa nhiều đơn hàng (khiến cho bị nhận nhầm trạng thái của đơn khác)
                    containers = page.locator(f'div:has-text("{job_id}")')
                    count = containers.count()
                    card = None
                    
                    for i in range(count - 1, -1, -1):
                        container = containers.nth(i)
                        text = container.inner_text()
                        
                        # Đếm số lượng Job ID (6 số) trong thẻ này
                        ids_inside = set(re.findall(r'\b\d{6}\b', text))
                        if len(ids_inside) > 1:
                            # Nếu thẻ chứa nhiều hơn 1 đơn hàng -> Nó là thẻ List cha. Dừng lại, dùng thẻ con trước đó.
                            break
                        card = container

                    if card and card.is_visible():
                        text = card.inner_text()
                        # [FIX]: Bỏ "Tải Xuống" và "Download" khỏi điều kiện vì nút này luôn hiển thị trên UI kể cả khi đang xử lý
                        if any(x in text for x in ["Đã xong", "Success"]):
                            print(f"🎉 Job {job_id} HOÀN TẤT! Đang xử lý...")
                            # ... (giữ nguyên logic xử lý thành công)
                            try:
                                # Bước 1: Thử lấy link trực tiếp từ nút Tải TRONG CARD NÀY
                                ext_url = None
                                video_element = card.locator('video source, video[src]').first
                                if video_element.count() > 0 and video_element.is_visible():
                                    ext_url = video_element.get_attribute('src') or video_element.get_attribute('currentSrc')

                                download_link = card.locator(
                                    'a[href*="proxy/files"], a[href*="download"], a:has-text("Tải"), a:has-text("Download")'
                                ).first
                                if not ext_url and download_link.count() > 0 and download_link.is_visible():
                                    ext_url = download_link.get_attribute('href', timeout=3000)

                                # Bước 3 (Dự phòng): Click vào card để vào trang chi tiết lấy video
                                if not ext_url:
                                    try:
                                        print(f"🖱️ Click vào Job {job_id} để lấy link video...")
                                        card.click()
                                        page.wait_for_timeout(5000)
                                        # [FIX]: Kiểm tra xem trang CÓ THỰC SỰ CHUYỂN HAY KHÔNG
                                        if "dashboard" not in page.url:
                                            video_element = page.locator('video source, video[src]').first
                                            if video_element.count() > 0:
                                                ext_url = video_element.get_attribute('src')
                                            page.goto(DASHBOARD_URL) # Quay lại Dashboard
                                            time.sleep(3)
                                        else:
                                            print(f"❌ Nút click không chuyển trang. Bỏ qua để tránh lấy nhầm video ngoài Dashboard.")
                                    except Exception as e:
                                        print(f"❌ Lỗi khi vào trang chi tiết cho Job {job_id}: {e}")

                                # Bước 3: Tải file nếu đã có link (kèm cookies)
                                if ext_url:
                                    if not ext_url.startswith('http'):
                                        ext_url = AIDANCING_ORIGIN + ext_url

                                    dl_btn = download_link if (download_link.count() > 0 and ext_url) else None
                                    local_vid = download_aidancing_result(
                                        browser, page, ext_url, f"res_{doc.id}.mp4", download_locator=dl_btn
                                    )
                                    if local_vid:
                                        r2_url = upload_to_r2(local_vid)
                                        if r2_url:
                                            db.collection('orders').document(doc.id).update({
                                                'status': 'completed',
                                                'resultLink': r2_url,
                                                'updatedAt': firestore.SERVER_TIMESTAMP
                                            })
                                            print(f"✅ ĐÃ TRẢ HÀNG CHO ĐƠN {doc.id}")
                                            
                                            # Gửi thông báo Telegram: Đơn hàng hoàn thành
                                            try:
                                                order_data = doc.to_dict()
                                                short_id = doc.id[-6:].upper()
                                                user_name = order_data.get('userName', 'Khách hàng')
                                                user_email = order_data.get('userEmail', 'N/A')
                                                char_img = order_data.get('characterImageLink', '')
                                                msg = (
                                                    f"✅ <b>ĐƠN HÀNG HOÀN THÀNH</b>\n\n"
                                                    f"🆔 Mã đơn: #{short_id}\n"
                                                    f"👤 Khách: {user_name}\n"
                                                    f"📧 Email: {user_email}\n"
                                                )
                                                if char_img:
                                                    msg += f"📸 Ảnh đầu vào: <a href=\"{char_img}\">Xem ảnh gốc</a>\n"
                                                msg += f"📹 Kết quả: <a href=\"{r2_url}\">Xem video kết quả</a>"
                                                send_telegram_message(msg)
                                            except Exception as tele_err:
                                                print(f"⚠️ Lỗi gửi thông báo Telegram hoàn thành: {tele_err}")

                                            # Gửi mail thông báo tự động cho khách hàng
                                            try:
                                                order_data = doc.to_dict()
                                                send_completion_email(doc.id, order_data, r2_url)
                                            except Exception as mail_err:
                                                print(f"⚠️ Không gửi được email thông báo: {mail_err}")
                                                
                                            os.remove(local_vid)
                            except Exception as e:
                                print(f"⚠️ Lỗi xử lý Job {job_id}: {e}")
                            finally:
                                close_extra_aidancing_tabs(browser, page)
                                if page.url != DASHBOARD_URL:
                                    try:
                                        page.goto(DASHBOARD_URL, wait_until='domcontentloaded', timeout=60000)
                                        time.sleep(2)
                                    except Exception:
                                        pass
                        elif any(x in text for x in ["Chưa thành công", "Thất bại", "Failed", "Error"]):
                            print(f"❌ Job {job_id} THẤT BẠI TRÊN AIDANCING!")
                            order_data = doc.to_dict()
                            
                            # Hoàn tiền cho khách
                            cost_coins = order_data.get('costCoins', 0)
                            user_id = order_data.get('userId')
                            if cost_coins > 0 and user_id:
                                try:
                                    db.collection('users').document(user_id).update({
                                        'coins': firestore.Increment(cost_coins)
                                    })
                                    print(f"💰 Đã hoàn lại {cost_coins} coin cho user {user_id}")
                                except Exception as e:
                                    print(f"⚠️ Lỗi khi hoàn tiền cho user {user_id}: {e}")

                            db.collection('orders').document(doc.id).update({
                                'status': 'failed',
                                'adminNote': firestore.DELETE_FIELD,
                                'systemNote': user_note_for_render_failure(text),
                                'updatedAt': firestore.SERVER_TIMESTAMP
                            })

                            # Gửi thông báo Telegram: Đơn hàng thất bại
                            try:
                                order_data = doc.to_dict()
                                short_id = doc.id[-6:].upper()
                                user_name = order_data.get('userName', 'Khách hàng')
                                user_email = order_data.get('userEmail', 'N/A')
                                msg = (
                                    f"❌ <b>ĐƠN HÀNG THẤT BẠI</b>\n\n"
                                    f"🆔 Mã đơn: #{short_id}\n"
                                    f"👤 Khách: {user_name}\n"
                                    f"📧 Email: {user_email}\n"
                                    f"📝 Lý do: Ảnh/video tham chiếu không hợp lệ."
                                )
                                send_telegram_message(msg)
                            except Exception as tele_err:
                                print(f"⚠️ Lỗi gửi thông báo Telegram thất bại: {tele_err}")
                        else:
                            print(f"⏳ Job {job_id} vẫn đang render...")
                browser.close()
    except Exception as e:
        print(f"❌ Lỗi monitor: {e}")

def on_pending_orders_snapshot(keys, changes, read_time):
    if not is_bot_enabled():
        return
    _ensure_pending_worker()
    with _pending_queue_lock:
        for ch in changes:
            if ch.type.name != 'ADDED':
                continue
            oid = ch.document.id
            with _submitting_orders_lock:
                if oid in _submitting_orders:
                    continue
            if oid not in _pending_order_queue:
                _pending_order_queue.append(oid)
                print(f"📋 Xếp hàng nạp đơn: {oid} (còn {len(_pending_order_queue)} trong queue)")


def _enqueue_pending_rescan():
    """Đưa đơn pending vào queue (khởi động bot hoặc retry sau lỗi mạng)."""
    if not is_bot_enabled():
        return
    _ensure_pending_worker()
    try:
        docs = db.collection('orders').where(
            filter=FieldFilter("status", "==", "pending")
        ).limit(20).stream()
        with _pending_queue_lock:
            for doc in docs:
                oid = doc.id
                if _pending_submit_backoff_active(oid):
                    continue
                with _submitting_orders_lock:
                    if oid in _submitting_orders:
                        continue
                if oid not in _pending_order_queue:
                    _pending_order_queue.append(oid)
                    print(f"🔄 Hàng đợi thử lại đơn pending: {oid}")
    except Exception as e:
        print(f"⚠️ rescan pending: {e}")


def _rescan_pending_orders_loop():
    """Thử lại đơn pending sau khi session Aidancing được sửa (mỗi 5 phút)."""
    while True:
        time.sleep(SESSION_ERROR_BACKOFF_SEC)
        _enqueue_pending_rescan()

def start_bot():
    global BOT_NAME
    parser = argparse.ArgumentParser(description='Kaling order bot — aidancing.net + xiaoyang')
    parser.add_argument('--name', required=True, help='Tên bot duy nhất (vd: aidancing-vps1, bot-may-nha)')
    parser.add_argument('--mode', choices=['browser', 'api', 'http'], default=None,
                        help='browser=Playwright; api/http=Pure HTTP (cookie + XY, không Chrome)')
    args = parser.parse_args()
    if args.mode:
        os.environ['BOT_MODE'] = args.mode
    BOT_NAME = normalize_bot_name(args.name)
    if not BOT_NAME:
        print("❌ Tên bot không hợp lệ. Dùng: python bot.py --name aidancing-vps1")
        sys.exit(1)

    print(f"📡 Kaling BOT [{BOT_NAME}] (v1.0 xy+ad - mode={os.environ.get('BOT_MODE', 'browser')}) đang khởi động...")
    cdp_url = os.environ.get("BOT_CDP_URL", "").strip()
    if cdp_url:
        if ensure_cdp_available(cdp_url):
            print(f"✅ Chrome CDP sẵn sàng: {cdp_url}")
        else:
            print(f"⚠️  BOT_CDP_URL={cdp_url} nhưng Chrome chưa mở CDP!")
            print("    → Mở Chrome CDP ở terminal KHÁC trước, giữ chạy, rồi bot mới nối được.")
    if xy_motion.enabled_for_bot(BOT_NAME):
        xy_motion.wire(
            db=db,
            bot_name=BOT_NAME,
            print=print,
            processing_cache=_processing_cache,
            processing_cache_lock=_processing_cache_lock,
            is_bot_enabled=is_bot_enabled,
            pending_submit_backoff_active=_pending_submit_backoff_active,
            submitting_orders_lock=_submitting_orders_lock,
            submitting_orders=_submitting_orders,
            browser_lock=browser_lock,
            submit_lock=submit_lock,
            download_file=download_file,
            session_error_backoff=_session_error_backoff,
            send_telegram_message=send_telegram_message,
            notify_internal_error_telegram=notify_internal_error_telegram,
            submit_to_aidancing=submit_to_aidancing,
            complete_order_with_video=_complete_order_with_video,
            min_render_sec=MIN_RENDER_SEC,
            skip_if_order_done=_skip_if_order_done,
            pop_processing_cache=_pop_processing_cache,
        )

    start_bot_control_listener()
    if xy_motion.enabled_for_bot(BOT_NAME):
        xy_motion.start_render_provider_listener()
    else:
        start_render_provider_listener()
    start_processing_listener()

    if not xy_motion.enabled_for_bot(BOT_NAME):
        try:
            keys = load_api_keys()
            print(f"✅ XiaoYang: {len(keys)} API key — phân chia credit + tải đơn")
            for i in range(len(keys)):
                cr, em = _xy_key_credits(i, force=True)
                print(f"   #{i} {em} | {cr} credits")
            from xiaoyang_direct import direct_worker_base
            dw = direct_worker_base()
            print(f"✅ XiaoYang direct worker: {dw or '(chưa cấu hình)'}")
        except Exception as e:
            print(f"⚠️  XiaoYang API: {e}")

    if use_api_mode():
        try:
            _get_http_client()
            print("✅ Pure HTTP Aidancing — AIDANCING_COOKIE (không cần Chrome/CDP)")
        except ValueError as e:
            print(f"⚠️  Chưa cấu hình cookie Aidancing: {e}")
        if xy_motion.enabled_for_bot(BOT_NAME):
            xy_motion.log_accounts_on_startup()

    def monitor_loop():
        while True:
            ad_eligible, xy_eligible, vae_eligible, tool98_eligible, processing = _processing_monitor_state()
            if is_bot_enabled():
                check_finished_orders()
            if use_api_mode():
                sleep_sec = _monitor_sleep_seconds(
                    len(ad_eligible) + len(xy_eligible) + len(vae_eligible) + len(tool98_eligible),
                    processing,
                )
            else:
                sleep_sec = 60 if processing else int(os.environ.get("BOT_POLL_IDLE_SEC", "300"))
            time.sleep(sleep_sec)

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=_rescan_pending_orders_loop, daemon=True).start()

    db.collection('orders').where(filter=FieldFilter("status", "==", "pending")).on_snapshot(on_pending_orders_snapshot)
    _enqueue_pending_rescan()

    print(f"🟢 [{BOT_NAME}] Đang trực — lắng nghe Firestore (bật/tắt từ Admin)...")
    while True:
        time.sleep(1)

if __name__ == "__main__":
    start_bot()
