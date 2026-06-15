"""
XiaoYang web multi-account + Aidancing fallback cho kaling (web3).
Gọi xy_wire() từ bot.py khi khởi động.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone

import requests
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from project_env import get_env, load_project_env
from xiaoyang_web import XiaoyangAuthError, XiaoyangWebClient, XiaoyangWebError
from pathlib import Path
from videoaieasy_web import (
    VideoAiEasyClient,
    VideoAiEasyAuthError,
    VideoAiEasyError,
    MODEL_KLING_26,
    MODEL_KLING_30,
    prepare_character_image_for_vae,
    resolution_for_order,
)
from tool98_api import (
    Tool98ApiError,
    Tool98Client,
    load_media_input,
    prepare_motion_video_source,
    probe_video_duration_seconds,
    resolve_motion_duration_seconds,
    trim_video_to_seconds,
    extract_video_segment,
    concat_video_files,
)

load_project_env()

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
VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT = int(get_env("VIDEOAIEASY_MAX_CONCURRENT", "4"))
AIDANCING_TURBO_MODEL_IDS = frozenset({"117"})
AIDANCING_FAST_MODEL_IDS = frozenset({"124", "125"})
TOOL98_ECONOMY_MODEL_IDS = frozenset({"126"})
TOOL98_RESOLUTION = "720P"
TOOL98_ECONOMY_PROFILE = get_env("TOOL98_ECONOMY_PROFILE", "gen_03").strip() or "gen_03"
TOOL98_FALLBACK_MIN_COMPLETED_ORDERS = 3
TOOL98_FALLBACK_MAX_VIDEO_SEC = 15.0
XIAOYANG_MODAL_STANDARD = "motion_v26"
XIAOYANG_MODAL_TURBO = "motion_v30"
XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT = int(get_env("XIAOYANG_MAX_CONCURRENT", "4"))
VAE_DURATION_FAST_SEC = 5
VAE_DURATION_TURBO_SEC = 10
VAE_SPLIT_SEGMENT_SEC = 5
VAE_SPLIT_MODE_DUAL_5S = "dual_5s"

from user_order_notes import USER_NOTE_FILES_MISSING, user_note_for_render_failure, user_note_for_videoaieasy_failure

_g: dict = {}
_active_render_provider = RENDER_PROVIDER_VIDEOAIEASY
_active_render_provider_lock = threading.Lock()
_xy_web_clients: dict = {}
_xy_web_clients_lock = threading.Lock()
_xy_inflight: dict = {}
_xy_inflight_lock = threading.Lock()
_xy_accounts_cache = None
_xy_accounts_cache_lock = threading.Lock()
_vae_web_clients: dict = {}
_vae_web_clients_lock = threading.Lock()
_vae_inflight: dict = {}
_vae_inflight_lock = threading.Lock()
_vae_accounts_cache = None
_vae_accounts_cache_lock = threading.Lock()
_tool98_client = None
_tool98_client_lock = threading.Lock()


def wire(**kwargs):
    _g.update(kwargs)


def _submit_engine_lock():
    return _g.get("submit_lock") or _g.get("browser_lock")


def enabled_for_bot(bot_name: str | None) -> bool:
    return bool(bot_name and "kaling" in bot_name.lower())


def get_active_render_provider():
    with _active_render_provider_lock:
        return _active_render_provider


def apply_render_provider_from_bot_data(data: dict, source=""):
    global _active_render_provider
    p = (data.get("activeRenderProvider") or data.get("activeProvider") or RENDER_PROVIDER_VIDEOAIEASY)
    p = p.strip().lower()
    if p not in _RENDER_PROVIDERS:
        p = RENDER_PROVIDER_VIDEOAIEASY
    with _active_render_provider_lock:
        prev = _active_render_provider
        _active_render_provider = p
    if p != prev:
        suffix = f" ({source})" if source else ""
        print(f"\n🔀 Render provider: {prev} → {p}{suffix} (đơn đang chạy giữ engine cũ)\n")


def start_render_provider_listener():
    db = _g["db"]
    bot_name = _g["bot_name"]
    initial = RENDER_PROVIDER_VIDEOAIEASY
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


def _use_videoaieasy() -> bool:
    return enabled_for_bot(_g.get("bot_name"))


def _videoaieasy_model_for_order(order_data: dict) -> str:
    model_id = str((order_data or {}).get("modelId") or "").strip()
    if model_id in AIDANCING_TURBO_MODEL_IDS:
        return MODEL_KLING_30
    return MODEL_KLING_26


def _vae_duration_for_order(order_data: dict) -> int:
    data = order_data or {}
    explicit = data.get("vaeDurationSec")
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            pass
    model_id = str(data.get("modelId") or "").strip()
    if model_id in AIDANCING_TURBO_MODEL_IDS:
        return VAE_DURATION_TURBO_SEC
    return VAE_DURATION_FAST_SEC


def _is_vae_split_order(order_data: dict | None) -> bool:
    return (order_data or {}).get("vaeSplitMode") == VAE_SPLIT_MODE_DUAL_5S


def _vae_split_part_path(order_id: str, part: int) -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"kaling_vae_split_{order_id}_part{int(part)}.mp4",
    )


def _mark_vae_split_processing(
    doc_ref,
    job_id: str,
    *,
    part: int,
    videoaieasy_account: str,
    videoaieasy_account_email: str,
):
    payload = {
        "status": "processing",
        "renderProvider": RENDER_PROVIDER_VIDEOAIEASY,
        "videoaieasyJobId": str(job_id),
        "vaeSplitMode": VAE_SPLIT_MODE_DUAL_5S,
        "vaeSplitPart": int(part),
        "vaeSplitStage": f"part{int(part)}_processing",
        "vaeSplitJobIds": firestore.ArrayUnion([str(job_id)]),
        "videoaieasyAccount": str(videoaieasy_account),
        "videoaieasyAccountEmail": str(videoaieasy_account_email),
        "submittedAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    doc_ref.update(payload)


def _submit_vae_split_part(order_id: str, part: int, account: dict) -> bool:
    """Nạp 1 phần (0 hoặc 1) của đơn split 2×5s."""
    account_id = account["id"]
    account_email = account.get("email", "")
    nick_label = account_email or account_id
    seg = VAE_SPLIT_SEGMENT_SEC
    start = part * seg

    db = _g["db"]
    doc_ref = db.collection("orders").document(order_id)
    doc = doc_ref.get()
    if not doc.exists:
        return False
    data = doc.to_dict() or {}
    if data.get("status") not in ("pending", "processing"):
        return False

    img_url = (data.get("characterImageLink") or "").strip()
    vid_url = (data.get("referenceVideoLink") or "").strip()
    if not img_url or not vid_url:
        print(f"❌ Split thiếu link ảnh/video — {order_id}")
        return False

    char_path = None
    vid_path = None
    vae_char_path = None
    vae_char_is_tmp = False
    seg_path = None
    seg_is_tmp = False
    download_file = _g["download_file"]

    try:
        print(
            f"\n⚡ [VAE Split part {part}] {order_id} — nick {nick_label} "
            f"({start}s–{start + seg}s)..."
        )
        api = _get_vae_web_client(account_id)
        _ensure_vae_web_session(api, account_email, account.get("password"))

        for attempt in range(1, 3):
            if attempt > 1:
                print(f"🔄 Thử tải file lần {attempt}...")
            char_path = download_file(img_url, f"char_{order_id}.png")
            vid_path = download_file(vid_url, f"vid_{order_id}.mp4")
            if char_path and vid_path:
                break
            time.sleep(2)
        if not char_path or not vid_path:
            raise VideoAiEasyError("Không tải được ảnh/video từ link đơn hàng")

        aspect = (data.get("aspectRatio") or "9:16").strip()
        vae_char_path, vae_char_is_tmp = prepare_character_image_for_vae(
            char_path, aspect_ratio=aspect
        )

        fd, seg_out = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        seg_path = extract_video_segment(
            Path(vid_path),
            start_sec=start,
            duration_sec=seg,
            output=Path(seg_out),
        )
        seg_is_tmp = True
        print(f"✂️ Đoạn motion part {part}: {start}s → {start + seg}s")

        prompt = (data.get("prompt") or get_env(
            "VIDEOAIEASY_PROMPT", "Follow the reference motion naturally"
        )).strip()
        image_url = api.upload_file(vae_char_path, kind="image")
        video_url = api.upload_file(str(seg_path), kind="video")
        job_id = api.create_motion_job(
            input_image_url=image_url,
            driving_video_url=video_url,
            prompt=prompt,
            model_id=MODEL_KLING_26,
            resolution=resolution_for_order(data),
        )
        print(f"🆔 [VAE Split/{nick_label}] part {part} job: {job_id}")
        _mark_vae_split_processing(
            doc_ref,
            job_id,
            part=part,
            videoaieasy_account=account_id,
            videoaieasy_account_email=account_email,
        )
        _g.get("session_error_backoff", {}).pop(order_id, None)
        return True
    except (requests.RequestException, VideoAiEasyAuthError, VideoAiEasyError) as e:
        print(f"❌ VAE Split part {part} thất bại {order_id}: {e}")
        if isinstance(e, VideoAiEasyAuthError):
            _reset_vae_web_client(account_id)
        _g["notify_internal_error_telegram"](
            order_id, data, str(e), f"submit vae split part{part}/{nick_label}"
        )
        return False
    finally:
        if vae_char_is_tmp and vae_char_path and os.path.exists(vae_char_path):
            os.remove(vae_char_path)
        if seg_is_tmp and seg_path and os.path.exists(seg_path):
            os.remove(seg_path)
        if char_path and os.path.exists(char_path):
            os.remove(char_path)
        if vid_path and os.path.exists(vid_path):
            os.remove(vid_path)


def _videoaieasy_account_id(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def load_videoaieasy_accounts():
    global _vae_accounts_cache
    with _vae_accounts_cache_lock:
        if _vae_accounts_cache is not None:
            return _vae_accounts_cache
        accounts = []
        raw = (get_env("VIDEOAIEASY_ACCOUNTS") or "").strip()
        if raw:
            if raw.startswith("["):
                import json as _json
                try:
                    for item in _json.loads(raw):
                        email = (item.get("email") or "").strip()
                        password = item.get("password") or ""
                        if email and password:
                            accounts.append({
                                "id": _videoaieasy_account_id(email),
                                "email": email,
                                "password": password,
                            })
                except Exception as e:
                    print(f"⚠️ VIDEOAIEASY_ACCOUNTS JSON lỗi: {e}")
            else:
                for part in raw.split(","):
                    part = part.strip()
                    if ":" not in part:
                        continue
                    email, password = part.split(":", 1)
                    email, password = email.strip(), password.strip()
                    if email and password:
                        accounts.append({
                            "id": _videoaieasy_account_id(email),
                            "email": email,
                            "password": password,
                        })
        if not accounts:
            email = (get_env("VIDEOAIEASY_EMAIL") or "").strip()
            password = get_env("VIDEOAIEASY_PASSWORD") or ""
            if email and password:
                accounts.append({
                    "id": _videoaieasy_account_id(email),
                    "email": email,
                    "password": password,
                })
        _vae_accounts_cache = accounts
        return accounts


def _get_vae_web_client(account_id: str) -> VideoAiEasyClient:
    key = account_id.lower()
    with _vae_web_clients_lock:
        if key not in _vae_web_clients:
            _vae_web_clients[key] = VideoAiEasyClient(account_id=key)
        return _vae_web_clients[key]


def _reset_vae_web_client(account_id: str | None = None):
    with _vae_web_clients_lock:
        if account_id:
            _vae_web_clients.pop(account_id.lower(), None)
        else:
            _vae_web_clients.clear()


def _ensure_vae_web_session(api: VideoAiEasyClient, email: str, password: str):
    return api.ensure_session(email, password)


def _vae_inflight_inc(account_id: str):
    with _vae_inflight_lock:
        _vae_inflight[account_id] = _vae_inflight.get(account_id, 0) + 1


def _vae_inflight_dec(account_id: str):
    with _vae_inflight_lock:
        n = _vae_inflight.get(account_id, 0) - 1
        if n <= 0:
            _vae_inflight.pop(account_id, None)
        else:
            _vae_inflight[account_id] = n


def _count_vae_processing_for_account(account_id: str) -> int:
    db = _g["db"]
    cache = _g.get("processing_cache", {})
    cache_lock = _g["processing_cache_lock"]
    cache_count = 0
    with cache_lock:
        for doc in cache.values():
            d = doc.to_dict() or {}
            if d.get("status") == "processing" and d.get("videoaieasyAccount") == account_id:
                cache_count += 1
    try:
        q = db.collection("orders").where(
            filter=FieldFilter("status", "==", "processing")
        ).where(
            filter=FieldFilter("videoaieasyAccount", "==", account_id)
        )
        db_count = sum(1 for _ in q.stream())
        return max(cache_count, db_count)
    except Exception as e:
        print(f"⚠️ Đếm đơn VideoAiEasy nick {account_id}: {e}")
        return cache_count


def _vae_active_count(account_id: str) -> int:
    with _vae_inflight_lock:
        inflight = _vae_inflight.get(account_id, 0)
    return _count_vae_processing_for_account(account_id) + inflight


def _pick_videoaieasy_account():
    accounts = load_videoaieasy_accounts()
    if not accounts:
        return None
    best = None
    best_count = VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT
    for acc in accounts:
        c = _vae_active_count(acc["id"])
        if c < VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT and c < best_count:
            best = acc
            best_count = c
    return best


def _videoaieasy_account_lookup(account_id: str):
    for acc in load_videoaieasy_accounts():
        if acc["id"] == account_id:
            return acc
    return None


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


def _is_tool98_economy_order(order_data: dict) -> bool:
    return str((order_data or {}).get("modelId") or "").strip() in TOOL98_ECONOMY_MODEL_IDS


def _should_route_tool98(order_data: dict) -> bool:
    return _is_tool98_economy_order(order_data) or bool((order_data or {}).get("tool98Fallback"))


def _is_fast_order(order_data: dict) -> bool:
    model_id = str((order_data or {}).get("modelId") or "").strip()
    return model_id in AIDANCING_FAST_MODEL_IDS or not model_id


def _user_has_min_completed_orders(user_id: str, minimum: int = TOOL98_FALLBACK_MIN_COMPLETED_ORDERS) -> bool:
    user_id = (user_id or "").strip()
    if not user_id or minimum <= 0:
        return False
    db = _g["db"]
    q = (
        db.collection("orders")
        .where(filter=FieldFilter("userId", "==", user_id))
        .where(filter=FieldFilter("status", "==", "completed"))
        .limit(minimum)
    )
    return len(list(q.stream())) >= minimum


def _order_video_duration_sec(order_data: dict) -> float | None:
    vid_url = (order_data.get("referenceVideoLink") or "").strip()
    if not vid_url:
        return None
    session = None
    if _tool98_enabled():
        try:
            session = _get_tool98_client().session
        except Tool98ApiError:
            session = None
    return probe_video_duration_seconds(vid_url, session=session)


def _order_video_under_tool98_max(order_data: dict) -> bool:
    duration = _order_video_duration_sec(order_data)
    if duration is None:
        return False
    return duration <= TOOL98_FALLBACK_MAX_VIDEO_SEC + 0.25


def _can_tool98_fallback(order_data: dict) -> bool:
    if not _tool98_enabled():
        return False
    if (order_data or {}).get("tool98Fallback"):
        return False
    if not _is_fast_order(order_data):
        return False
    user_id = (order_data.get("userId") or "").strip()
    if not _user_has_min_completed_orders(user_id):
        return False
    if not _order_video_under_tool98_max(order_data):
        return False
    img_url = (order_data.get("characterImageLink") or "").strip()
    vid_url = (order_data.get("referenceVideoLink") or "").strip()
    return bool(img_url and vid_url)


def _prepare_order_for_tool98_fallback(doc_ref) -> None:
    payload = {
        "status": "pending",
        "tool98Fallback": True,
        "renderProvider": firestore.DELETE_FIELD,
        "xiaoyangTaskId": firestore.DELETE_FIELD,
        "xiaoyangAccount": firestore.DELETE_FIELD,
        "xiaoyangAccountEmail": firestore.DELETE_FIELD,
        "xiaoyangSubmitMode": firestore.DELETE_FIELD,
        "videoaieasyJobId": firestore.DELETE_FIELD,
        "videoaieasyAccount": firestore.DELETE_FIELD,
        "videoaieasyAccountEmail": firestore.DELETE_FIELD,
        "aidancingJobId": firestore.DELETE_FIELD,
        "tool98JobId": firestore.DELETE_FIELD,
        "submittedAt": firestore.DELETE_FIELD,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    doc_ref.update(payload)
    pop = _g.get("pop_processing_cache")
    if pop:
        pop(doc_ref.id)


def fail_or_tool98_fallback(doc, order_data, err_detail, system_note, context: str) -> bool:
    """Return True when fallback started or order was failed after fallback attempt."""
    if not _can_tool98_fallback(order_data):
        return False
    order_id = doc.id
    print(
        f"↪️ [Tool98 fallback] Đơn {order_id} — {context}: "
        f"{str(err_detail)[:160]}"
    )
    db = _g["db"]
    doc_ref = db.collection("orders").document(order_id)
    _prepare_order_for_tool98_fallback(doc_ref)
    if submit_to_tool98(order_id):
        return True
    fresh_doc = doc_ref.get()
    fresh_data = fresh_doc.to_dict() or order_data
    _fail_order_processing(
        fresh_doc,
        fresh_data,
        f"Tool98 fallback submit failed after: {err_detail}",
        system_note,
        context,
    )
    return True


def _fail_or_tool98_fallback(doc, order_data, err_detail, system_note, context: str):
    if fail_or_tool98_fallback(doc, order_data, err_detail, system_note, context):
        return
    _fail_order_processing(doc, order_data, err_detail, system_note, context)


def _tool98_enabled() -> bool:
    return bool(get_env("TOOL98_LICENSE_KEY", "").strip())


def _get_tool98_client() -> Tool98Client:
    global _tool98_client
    with _tool98_client_lock:
        if _tool98_client is None:
            key = get_env("TOOL98_LICENSE_KEY", "").strip()
            if not key:
                raise Tool98ApiError("Missing TOOL98_LICENSE_KEY")
            base = get_env("TOOL98_BASE_URL", "https://ai.tool98.com").strip()
            _tool98_client = Tool98Client(license_key=key, base_url=base)
        return _tool98_client


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


def split_monitor_state(processing_cache: dict, min_render_sec: int, *, vae_min_render_sec: int | None = None):
    now = datetime.now(timezone.utc)
    ad_eligible = []
    xy_eligible = []
    vae_eligible = []
    tool98_eligible = []
    vae_wait = vae_min_render_sec if vae_min_render_sec is not None else min_render_sec
    for doc in processing_cache.values():
        d = doc.to_dict() or {}
        if d.get("status") != "processing":
            continue
        rp = _order_render_provider(d)
        wait_sec = vae_wait if rp == RENDER_PROVIDER_VIDEOAIEASY else min_render_sec
        submitted_at = d.get("submittedAt")
        if submitted_at and (now - submitted_at).total_seconds() <= wait_sec:
            continue
        if rp == RENDER_PROVIDER_TOOL98 and d.get("tool98JobId"):
            tool98_eligible.append(doc)
        elif rp == RENDER_PROVIDER_XIAOYANG and d.get("xiaoyangTaskId"):
            xy_eligible.append(doc)
        elif rp == RENDER_PROVIDER_VIDEOAIEASY and d.get("videoaieasyJobId"):
            vae_eligible.append(doc)
        else:
            job_id = d.get("aidancingJobId")
            if job_id and job_id != "MANUAL":
                ad_eligible.append(doc)
    return ad_eligible, xy_eligible, vae_eligible, tool98_eligible


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


def _mark_order_processing(
    doc_ref,
    job_id,
    *,
    provider,
    xiaoyang_account=None,
    xiaoyang_account_email=None,
    videoaieasy_account=None,
    videoaieasy_account_email=None,
):
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
    elif provider == RENDER_PROVIDER_VIDEOAIEASY:
        payload["videoaieasyJobId"] = str(job_id)
        if videoaieasy_account:
            payload["videoaieasyAccount"] = str(videoaieasy_account)
        if videoaieasy_account_email:
            payload["videoaieasyAccountEmail"] = str(videoaieasy_account_email)
    elif provider == RENDER_PROVIDER_TOOL98:
        payload["tool98JobId"] = str(job_id)
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
        with _submit_engine_lock():
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


def submit_to_videoaieasy(order_id: str, account: dict) -> bool:
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
    _vae_inflight_inc(account_id)
    success = False
    try:
        with _submit_engine_lock():
            db = _g["db"]
            doc_ref = db.collection("orders").document(order_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            if data.get("status") != "pending":
                return False

            nick_label = account_email or account_id
            print(f"\n⚡ [NẠP ĐƠN / VideoAiEasy] {order_id} — nick {nick_label}...")
            img_url = (data.get("characterImageLink") or "").strip()
            vid_url = (data.get("referenceVideoLink") or "").strip()
            if not img_url or not vid_url:
                print(f"❌ Thiếu link ảnh/video cho đơn {order_id}")
                return False

            char_path = None
            vid_path = None
            vae_char_path = None
            vae_char_is_tmp = False
            vid_upload_path = None
            vid_trim_tmp = None
            download_file = _g["download_file"]
            session_error_backoff = _g.get("session_error_backoff", {})
            try:
                model_id = _videoaieasy_model_for_order(data)
                max_sec = _vae_duration_for_order(data)
                tier = "Kling 3.0" if model_id == MODEL_KLING_30 else "Kling 2.6"
                prompt = (data.get("prompt") or get_env(
                    "VIDEOAIEASY_PROMPT", "Follow the reference motion naturally"
                )).strip()
                api = _get_vae_web_client(account_id)
                _ensure_vae_web_session(api, account_email, account.get("password"))
                print(
                    f"🚀 [VideoAiEasy/{nick_label}] {tier} — "
                    f"{max_sec}s 720p · modelId={data.get('modelId')} → {model_id}..."
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
                    raise VideoAiEasyError("Không tải được ảnh/video từ link đơn hàng")

                aspect = (data.get("aspectRatio") or "9:16").strip()
                vae_char_path, vae_char_is_tmp = prepare_character_image_for_vae(
                    char_path, aspect_ratio=aspect
                )
                vid_upload_path = vid_path
                dur = probe_video_duration_seconds(vid_path)
                if dur is None or dur > max_sec + 0.25:
                    import tempfile
                    fd, outp = tempfile.mkstemp(suffix=".mp4")
                    os.close(fd)
                    trim_video_to_seconds(
                        Path(vid_path), max_seconds=max_sec, output=Path(outp)
                    )
                    vid_upload_path = outp
                    vid_trim_tmp = outp
                    print(f"✂️ Cắt video motion → {max_sec}s (VAE)")

                print("📤 Upload ảnh lên videoaieasy.hdgr.online...")
                image_url = api.upload_file(vae_char_path, kind="image")
                print("📤 Upload video motion...")
                video_url = api.upload_file(vid_upload_path, kind="video")
                resolution = resolution_for_order(data)
                job_id = api.create_motion_job(
                    input_image_url=image_url,
                    driving_video_url=video_url,
                    prompt=prompt,
                    model_id=model_id,
                    resolution=resolution,
                )
                print(f"🆔 [VideoAiEasy/{nick_label}] job: {job_id}")
                _mark_order_processing(
                    doc_ref,
                    job_id,
                    provider=RENDER_PROVIDER_VIDEOAIEASY,
                    videoaieasy_account=account_id,
                    videoaieasy_account_email=account_email,
                )
                session_error_backoff.pop(order_id, None)
                print(f"✅ Đơn {order_id} → processing (VideoAiEasy, {nick_label})")
                try:
                    short_id = order_id[-6:].upper()
                    _g["send_telegram_message"](
                        f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b> (VideoAiEasy)\n\n"
                        f"🆔 Mã đơn: #{short_id}\n"
                        f"📧 Nick: {nick_label}\n"
                        f"🤖 Job: <code>{job_id}</code>\n"
                        f"⏳ Poll sau {_g.get('vae_min_render_sec', _g['min_render_sec']) // 60} phút, mỗi "
                        f"{int(get_env('VIDEOAIEASY_POLL_INTERVAL_SEC', '60'))}s..."
                    )
                except Exception:
                    pass
                success = True
            except (requests.RequestException, VideoAiEasyAuthError, VideoAiEasyError) as e:
                print(f"❌ Nạp VideoAiEasy thất bại {order_id} ({nick_label}): {e}")
                if isinstance(e, VideoAiEasyAuthError):
                    _reset_vae_web_client(account_id)
                _g["notify_internal_error_telegram"](
                    order_id, data, str(e), f"submit videoaieasy/{nick_label}"
                )
            finally:
                if vae_char_is_tmp and vae_char_path and os.path.exists(vae_char_path):
                    os.remove(vae_char_path)
                if vid_trim_tmp and os.path.exists(vid_trim_tmp):
                    os.remove(vid_trim_tmp)
                if char_path and os.path.exists(char_path):
                    os.remove(char_path)
                if vid_path and os.path.exists(vid_path):
                    os.remove(vid_path)
    finally:
        _vae_inflight_dec(account_id)
        with submitting_lock:
            submitting.discard(order_id)
    return success


def submit_to_videoaieasy_split(order_id: str, account: dict) -> bool:
    """Đơn test 2×5s: nạp part 0 (pending) hoặc part 1 (part1_pending)."""
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

    _vae_inflight_inc(account["id"])
    success = False
    try:
        with _submit_engine_lock():
            db = _g["db"]
            doc = db.collection("orders").document(order_id).get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            status = data.get("status")
            stage = data.get("vaeSplitStage")
            if status == "pending":
                success = _submit_vae_split_part(order_id, 0, account)
            elif status == "processing" and stage == "part1_pending":
                success = _submit_vae_split_part(order_id, 1, account)
    finally:
        _vae_inflight_dec(account["id"])
        with submitting_lock:
            submitting.discard(order_id)
    return success


def _try_submit_xiaoyang(order_id: str) -> bool:
    account = _pick_xiaoyang_account()
    if not account:
        print(
            f"📊 XiaoYang đầy slot ({XIAOYANG_MAX_CONCURRENT_PER_ACCOUNT} đơn/nick) — {order_id}"
        )
        return False
    return submit_to_xiaoyang(order_id, account)


def _try_submit_videoaieasy(order_id: str) -> bool:
    if not _use_videoaieasy():
        return False
    account = _pick_videoaieasy_account()
    if not account:
        print(f"📊 Không có nick VideoAiEasy hoặc đầy slot — {order_id}")
        return False
    db = _g["db"]
    doc = db.collection("orders").document(order_id).get()
    data = doc.to_dict() if doc.exists else {}
    if _is_vae_split_order(data):
        return submit_to_videoaieasy_split(order_id, account)
    return submit_to_videoaieasy(order_id, account)


def submit_to_tool98(order_id: str) -> bool:
    """Tool98 720P — legacy model 126 hoặc fallback ẩn sau khi engine chính fail."""
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

    success = False
    temp_trimmed = None
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
            if not _should_route_tool98(data):
                return False

            fallback = bool(data.get("tool98Fallback"))
            label = "Tool98 fallback" if fallback else "Tool98 tiết kiệm"
            print(f"\n⚡ [NẠP ĐƠN / {label}] {order_id}...")
            img_url = (data.get("characterImageLink") or "").strip()
            vid_url = (data.get("referenceVideoLink") or "").strip()
            if not img_url or not vid_url:
                _fail_order_processing(
                    doc, data,
                    "Thiếu characterImageLink hoặc referenceVideoLink",
                    USER_NOTE_FILES_MISSING,
                    "submit tool98",
                )
                return False

            if not _tool98_enabled():
                _fail_order_processing(
                    doc, data,
                    "Chưa cấu hình TOOL98_LICENSE_KEY",
                    user_note_for_render_failure("Hệ thống chưa sẵn sàng cho model tiết kiệm"),
                    "submit tool98",
                )
                return False

            try:
                client = _get_tool98_client()
                upload_video_source, temp_trimmed = prepare_motion_video_source(
                    vid_url,
                    resolution=TOOL98_RESOLUTION,
                    session=client.session,
                )
                duration = resolve_motion_duration_seconds(
                    upload_video_source,
                    resolution=TOOL98_RESOLUTION,
                    session=client.session,
                )
                aspect = (data.get("aspectRatio") or "").strip() or None
                print(
                    f"🚀 [Tool98] 720P profile={TOOL98_ECONOMY_PROFILE} "
                    f"duration={duration}s..."
                )
                image_obj = load_media_input(img_url, session=client.session)
                video_obj = load_media_input(upload_video_source, session=client.session)
                created = client.motion_copy(
                    image_obj,
                    video_obj,
                    resolution=TOOL98_RESOLUTION,
                    duration_seconds=duration,
                    aspect_ratio=aspect,
                    profile=TOOL98_ECONOMY_PROFILE,
                )
                job_id = str(created.get("job_id") or "").strip()
                if not job_id:
                    raise Tool98ApiError(f"Không nhận được job_id: {created}")
                print(f"🆔 [Tool98] job: {job_id}")
                _mark_order_processing(doc_ref, job_id, provider=RENDER_PROVIDER_TOOL98)
                _g.get("session_error_backoff", {}).pop(order_id, None)
                print(f"✅ Đơn {order_id} → processing ({label})")
                try:
                    short_id = order_id[-6:].upper()
                    _g["send_telegram_message"](
                        f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b> (Tool98 720P)\n\n"
                        f"🆔 Mã đơn: #{short_id}\n"
                        f"🤖 Job: <code>{job_id}</code>\n"
                        f"⏳ Poll sau {_g['min_render_sec'] // 60} phút..."
                    )
                except Exception:
                    pass
                success = True
            except (requests.RequestException, Tool98ApiError) as e:
                print(f"❌ Nạp Tool98 thất bại {order_id}: {e}")
                _g["notify_internal_error_telegram"](order_id, data, str(e), "submit tool98")
                _fail_order_processing(
                    doc, data,
                    f"Tool98 submit failed: {e}",
                    user_note_for_render_failure(str(e)),
                    "submit tool98",
                )
    finally:
        if temp_trimmed is not None:
            temp_trimmed.unlink(missing_ok=True)
        with submitting_lock:
            submitting.discard(order_id)
    return success


def _try_tool98_fallback_after_submit_exhausted(order_id: str) -> None:
    doc = _g["db"].collection("orders").document(order_id).get()
    if not doc.exists:
        return
    data = doc.to_dict() or {}
    if data.get("status") != "pending":
        return
    if (
        data.get("xiaoyangTaskId")
        or data.get("videoaieasyJobId")
        or data.get("aidancingJobId")
        or data.get("tool98JobId")
    ):
        return
    fail_or_tool98_fallback(
        doc,
        data,
        "Không nạp được qua engine chính",
        user_note_for_render_failure(None),
        "submit exhausted",
    )


def submit_order(order_id: str):
    """Nạp đơn — Kaling chỉ dùng VideoAiEasy (VAE)."""
    db = _g["db"]
    doc = db.collection("orders").document(order_id).get()
    if doc.exists:
        data = doc.to_dict() or {}
        if _should_route_tool98(data):
            _fail_order_processing(
                doc,
                data,
                "Model tiết kiệm không còn hỗ trợ",
                user_note_for_render_failure("Gói này đã ngừng. Chọn Model Nhanh hoặc Turbo."),
                "submit tool98 disabled",
            )
            return

    if enabled_for_bot(_g.get("bot_name")):
        _try_submit_videoaieasy(order_id)
        return

    provider = get_active_render_provider()

    if provider == RENDER_PROVIDER_AIDANCING:
        _g["submit_to_aidancing"](order_id)
    elif provider == RENDER_PROVIDER_XIAOYANG:
        if _try_submit_xiaoyang(order_id):
            return
        print(f"⚠️ XiaoYang không nạp được {order_id} → thử VideoAiEasy")
        if _try_submit_videoaieasy(order_id):
            return
        print(f"⚠️ VideoAiEasy không nạp được {order_id} → chuyển Aidancing")
        _g["submit_to_aidancing"](order_id, fallback_reason="xiaoyang_fail")
    elif provider == RENDER_PROVIDER_VIDEOAIEASY:
        if _try_submit_videoaieasy(order_id):
            return
        print(f"⚠️ VideoAiEasy không nạp được {order_id} → thử XiaoYang")
        if _try_submit_xiaoyang(order_id):
            return
        print(f"⚠️ XiaoYang không nạp được {order_id} → chuyển Aidancing")
        _g["submit_to_aidancing"](order_id, fallback_reason="videoaieasy_fail")
    else:
        _g["submit_to_aidancing"](order_id)

    _try_tool98_fallback_after_submit_exhausted(order_id)


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
            _fail_or_tool98_fallback(
                doc, order_data,
                f"XiaoYang task {task_id} FAIL: {err or ''}",
                user_note_for_render_failure(err),
                "render xiaoyang",
            )
        else:
            print(f"⏳ Task {task_id} vẫn {st}")


def _deliver_vae_job(doc, api: VideoAiEasyClient, job_id: str, complete) -> None:
    """Tải video VAE, trả hàng Kaling; xóa job trên VAE nếu trả hàng thành công."""
    local_vid = api.download_job(job_id, f"res_{doc.id}.mp4")
    if complete(doc, local_vid):
        api.try_delete_job(job_id)


def _submit_vae_split_part_locked(order_id: str, part: int, account: dict) -> bool:
    submitting_lock = _g["submitting_orders_lock"]
    submitting = _g["submitting_orders"]
    with submitting_lock:
        if order_id in submitting:
            return False
        submitting.add(order_id)
    try:
        with _submit_engine_lock():
            return _submit_vae_split_part(order_id, part, account)
    finally:
        with submitting_lock:
            submitting.discard(order_id)


def _poll_vae_split_order(doc, order_data, api, job_id: str, complete, skip_done) -> None:
    """Poll job VAE cho đơn split; part0 xong → nạp part1; part1 xong → ghép 10s."""
    part = int(order_data.get("vaeSplitPart") or 0)
    try:
        job = api.get_job(job_id)
    except VideoAiEasyError as e:
        print(f"❌ Poll VAE Split {job_id}: {e}")
        return

    status = (job.get("status") or "").lower()
    err = job.get("error_message")
    print(f"   [split part {part}] status={status}" + (f" — {err}" if err else ""))

    if status == "done":
        if skip_done and skip_done(doc.id, "đã completed"):
            return
        try:
            if part == 0:
                local = api.download_job(job_id, f"split_{doc.id}_p0.mp4")
                dest = _vae_split_part_path(doc.id, 0)
                shutil.move(local, dest)
                api.try_delete_job(job_id)
                print(f"✅ Split part 0 lưu → {dest}")
                db = _g["db"]
                db.collection("orders").document(doc.id).update({
                    "videoaieasyJobId": firestore.DELETE_FIELD,
                    "vaeSplitStage": "part1_pending",
                    "vaeSplitPart": 1,
                    "updatedAt": firestore.SERVER_TIMESTAMP,
                })
                acc_id = (order_data.get("videoaieasyAccount") or "").strip()
                acc = _videoaieasy_account_lookup(acc_id) if acc_id else None
                if not acc:
                    acc = _pick_videoaieasy_account()
                if acc:
                    _submit_vae_split_part_locked(doc.id, 1, acc)
                else:
                    print(f"⚠️ Không có nick VAE để nạp split part 1 — {doc.id}")
            elif part == 1:
                local1 = api.download_job(job_id, f"split_{doc.id}_p1.mp4")
                part0 = _vae_split_part_path(doc.id, 0)
                part1 = _vae_split_part_path(doc.id, 1)
                shutil.move(local1, part1)
                api.try_delete_job(job_id)
                fd, merged = tempfile.mkstemp(suffix=".mp4")
                os.close(fd)
                merged_path = Path(merged)
                print(f"🔗 Ghép split part0 + part1 → 10s...")
                concat_video_files([Path(part0), Path(part1)], merged_path)
                order_data = doc.to_dict() or {}
                order_data["vaeSplitStage"] = "merged"
                complete(doc, str(merged_path))
                for p in (part0, part1, str(merged_path)):
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
        except Exception as e:
            print(f"⚠️ Lỗi xử lý split {doc.id} part {part}: {e}")
            _g["notify_internal_error_telegram"](
                doc.id, order_data, str(e), f"split deliver part{part}"
            )
    elif status in ("failed", "expired"):
        _fail_order_processing(
            doc,
            order_data,
            f"VAE Split part {part} job {job_id} {status}: {err or ''}",
            user_note_for_videoaieasy_failure(err),
            f"render vae split part{part}",
        )
        for p in (0, 1):
            path = _vae_split_part_path(doc.id, p)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def poll_videoaieasy_orders(orders_to_check):
    skip_done = _g.get("skip_if_order_done")
    complete = _g["complete_order_with_video"]
    for doc in orders_to_check:
        order_data = doc.to_dict() or {}

        if _is_vae_split_order(order_data):
            stage = order_data.get("vaeSplitStage")
            job_id = str(order_data.get("videoaieasyJobId") or "").strip()
            if stage == "part1_pending" and not job_id:
                account_id = (order_data.get("videoaieasyAccount") or "").strip()
                acc = _videoaieasy_account_lookup(account_id) if account_id else None
                if not acc:
                    acc = _pick_videoaieasy_account()
                if acc:
                    print(f"⏩ Split part1_pending — nạp part 1 cho {doc.id}")
                    submit_to_videoaieasy_split(doc.id, acc)
                continue
            if not job_id:
                continue
            account_id = (order_data.get("videoaieasyAccount") or "").strip()
            nick = order_data.get("videoaieasyAccountEmail") or account_id
            part = order_data.get("vaeSplitPart", 0)
            print(
                f"🧐 VideoAiEasy Split part {part} — job {job_id} "
                f"(đơn {doc.id}, {nick})..."
            )
            api = None
            acc = _videoaieasy_account_lookup(account_id)
            for attempt in range(2):
                try:
                    if attempt > 0 and account_id:
                        _reset_vae_web_client(account_id)
                    api = _get_vae_web_client(account_id or "default")
                    if acc:
                        _ensure_vae_web_session(api, acc["email"], acc["password"])
                    break
                except VideoAiEasyAuthError as e:
                    if attempt == 0:
                        print(f"⚠️ Poll VAE Split {job_id}: {e} — thử login lại...")
                        continue
                    print(f"❌ Poll VAE Split {job_id}: {e}")
                except VideoAiEasyError as e:
                    print(f"❌ Poll VAE Split {job_id}: {e}")
                    break
            if not api:
                continue
            _poll_vae_split_order(doc, order_data, api, job_id, complete, skip_done)
            continue

        job_id = str(order_data.get("videoaieasyJobId") or "").strip()
        if not job_id:
            continue
        account_id = (order_data.get("videoaieasyAccount") or "").strip()
        nick = order_data.get("videoaieasyAccountEmail") or account_id
        print(f"🧐 VideoAiEasy — job {job_id} (đơn {doc.id}, {nick})...")
        api = None
        acc = _videoaieasy_account_lookup(account_id)
        job = None
        last_err = None
        for attempt in range(2):
            try:
                if attempt > 0 and account_id:
                    _reset_vae_web_client(account_id)
                api = _get_vae_web_client(account_id or "default")
                if acc:
                    _ensure_vae_web_session(api, acc["email"], acc["password"])
                job = api.get_job(job_id)
                break
            except VideoAiEasyAuthError as e:
                last_err = e
                if attempt == 0:
                    print(f"⚠️ Poll VideoAiEasy {job_id}: {e} — thử login lại...")
                    continue
                print(f"❌ Poll VideoAiEasy {job_id}: {e}")
            except VideoAiEasyError as e:
                last_err = e
                print(f"❌ Poll VideoAiEasy {job_id}: {e}")
                break
        if job is None:
            e = last_err
            if api and e and ("500" in str(e) or "404" in str(e)):
                try:
                    print(f"↪️ Thử download trực tiếp job {job_id}...")
                    _deliver_vae_job(doc, api, job_id, complete)
                    continue
                except Exception as dl_err:
                    print(f"⚠️ Download trực tiếp {job_id} thất bại: {dl_err}")
            continue
        status = (job.get("status") or "").lower()
        err = job.get("error_message")
        print(f"   status={status}" + (f" — {err}" if err else ""))
        if status == "done":
            if skip_done and skip_done(doc.id, "đã completed"):
                continue
            print(f"🎉 VideoAiEasy job {job_id} HOÀN TẤT — tải video...")
            try:
                _deliver_vae_job(doc, api, job_id, complete)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
        elif status in ("failed", "expired"):
            _fail_or_tool98_fallback(
                doc, order_data,
                f"VideoAiEasy job {job_id} {status}: {err or ''}",
                user_note_for_videoaieasy_failure(err),
                "render videoaieasy",
            )
        else:
            print(f"⏳ Job {job_id} vẫn {status}")


def poll_tool98_orders(orders_to_check):
    skip_done = _g.get("skip_if_order_done")
    complete = _g["complete_order_with_video"]
    try:
        client = _get_tool98_client()
    except Tool98ApiError as e:
        print(f"❌ Tool98 client: {e}")
        return
    for doc in orders_to_check:
        order_data = doc.to_dict() or {}
        job_id = str(order_data.get("tool98JobId") or "").strip()
        if not job_id:
            continue
        print(f"🧐 Tool98 — job {job_id} (đơn {doc.id})...")
        try:
            job = client.jobs_get(job_id)
        except Tool98ApiError as e:
            print(f"❌ Poll Tool98 {job_id}: {e}")
            continue
        status = str(job.get("status") or "").lower()
        err = job.get("error_message")
        print(f"   status={status}" + (f" — {err}" if err else ""))
        if status == "completed":
            results = job.get("results") or []
            if not results:
                _fail_order_processing(
                    doc, order_data,
                    f"Tool98 job {job_id} completed nhưng không có results",
                    user_note_for_render_failure("Không có video kết quả"),
                    "render tool98",
                )
                continue
            if skip_done and skip_done(doc.id, "đã completed"):
                continue
            print(f"🎉 Tool98 job {job_id} HOÀN TẤT — tải video...")
            local_vid = f"res_{doc.id}.mp4"
            try:
                from pathlib import Path
                client.download_media(results[0], Path(local_vid))
                complete(doc, local_vid)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
        elif status in ("failed", "canceled", "cancelled"):
            _fail_order_processing(
                doc, order_data,
                f"Tool98 job {job_id} {status}: {err or ''}",
                user_note_for_render_failure(err),
                "render tool98",
            )
        else:
            print(f"⏳ Tool98 job {job_id} vẫn {status}")


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
    if _use_videoaieasy():
        vae_accounts = load_videoaieasy_accounts()
        print(
            f"👥 VideoAiEasy accounts: {len(vae_accounts)} nick | "
            f"max {VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT} đơn/nick"
        )
        for acc in vae_accounts:
            try:
                api = _get_vae_web_client(acc["id"])
                me = _ensure_vae_web_session(api, acc["email"], acc["password"])
                active = _vae_active_count(acc["id"])
                print(
                    f"  ✅ {acc['email']} | credits: {me.get('credits', '?')} | "
                    f"đang chạy: {active}/{VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT}"
                )
            except Exception as e:
                print(f"  ⚠️  {acc['email']}: {e}")
    if _tool98_enabled():
        try:
            client = _get_tool98_client()
            client.jobs_list(include_params=False)
            print(
                f"✅ Tool98 Internal API — {client.base_url} "
                f"(profile tiết kiệm: {TOOL98_ECONOMY_PROFILE} @ {TOOL98_RESOLUTION})"
            )
        except Exception as e:
            print(f"  ⚠️  Tool98: {e}")
