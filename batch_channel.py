#!/usr/bin/env python3
"""
Batch kênh TikTok (Kaling) — chạy cron 3:00 Asia/Ho_Chi_Minh.

Pipeline mỗi video đăng ngày hôm qua (VN):
  tải video → cắt frame → Meo3 thay đồ full bộ → tạo đơn motion pending (Kling 2.6 Pro 10 coin).

Cần .env: VIDEOAIEASY_ACCOUNTS + R2_* + serviceAccountKey.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
import firebase_admin
from firebase_admin import credentials, firestore

from project_env import get_env, load_project_env

load_project_env()

from client_version import APP_CLIENT_VERSION
from videoaieasy_web import (
    VideoAiEasyClient,
    VideoAiEasyAuthError,
    VideoAiEasyError,
    get_batch_vae_client,
    normalize_vae_public_url,
    poll_vae_job,
)
from xiaoyang_direct import DirectMediaError, upload_result_file

ROOT = Path(__file__).resolve().parent
CONFIG_DOC = "default"  # legacy admin doc; user configs use Firebase uid
CONFIG_COLLECTION = "batchChannelConfig"
RUNS_COLLECTION = "batchChannelRuns"
ALLOWLIST_COLLECTION = "batchChannelAllowlist"
TIKWM_USER_POSTS = "https://kaling.cloud/api/tiktok-channel"
VN_TZ = "Asia/Ho_Chi_Minh"
# Batch model presets (auto-create video popup)
BATCH_MODEL_PRESETS = {
    "vae10": {
        "modelId": "124",
        "renderProvider": "roboneo",
        "vaeDurationSec": 10,
        "vaeResolution": "720p",
        "maxVideoSec": 10,
        "costCoins": 3.1,
        "serviceLabel": "Kling 2.6 (10s)",
    },
    "vae20": {
        "modelId": "125",
        "renderProvider": "videoaieasy",
        "vaeDurationSec": 20,
        "vaeResolution": "720p",
        "maxVideoSec": 20,
        "costCoins": 6.1,
        "serviceLabel": "Kling 2.6 Pro (20s)",
    },
}
# Legacy defaults (vae20)
BATCH_RENDER_PROVIDER = "videoaieasy"
BATCH_MODEL_ID = "125"
BATCH_VAE_DURATION_SEC = 20
BATCH_VAE_RESOLUTION = "720p"
BATCH_MAX_VIDEO_SEC = 20
BATCH_ORDER_COST_COINS = 6.1
STALE_RUNNING_RUN_HOURS = 3


class InsufficientCoinsError(RuntimeError):
    """User không đủ coin trước khi batch tạo ảnh / đơn."""
    pass

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore


def _vn_now() -> datetime:
    if ZoneInfo:
        return datetime.now(ZoneInfo(VN_TZ))
    return datetime.utcnow() + timedelta(hours=7)


def _normalize_allowlist_email(email: str) -> str:
    return (email or "").strip().lower()


def _is_batch_channel_allowlisted(db, email: str) -> bool:
    key = _normalize_allowlist_email(email)
    if not key:
        return False
    snap = db.collection(ALLOWLIST_COLLECTION).document(key).get()
    return snap.exists


def _yesterday_vn_range() -> tuple[int, int]:
    """Unix seconds [start, end) for yesterday 00:00–24:00 VN."""
    now = _vn_now()
    y = (now.date() - timedelta(days=1))
    if ZoneInfo:
        z = ZoneInfo(VN_TZ)
        start = int(datetime(y.year, y.month, y.day, 0, 0, 0, tzinfo=z).timestamp())
        end = int(datetime(y.year, y.month, y.day, 23, 59, 59, tzinfo=z).timestamp()) + 1
    else:
        start = int(datetime(y.year, y.month, y.day, 0, 0, 0).timestamp()) - 7 * 3600
        end = start + 86400
    return start, end


def parse_tiktok_username(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty_channel")
    if s.startswith("@"):
        return s[1:].split("/")[0].strip()
    if "tiktok.com" in s:
        m = re.search(r"tiktok\.com/@([^/?#]+)", s, re.I)
        if m:
            return m.group(1).strip()
    return s.split("/")[0].strip().lstrip("@")


def fetch_channel_videos(username: str, *, max_pages: int = 5) -> list[dict]:
    username = parse_tiktok_username(username)
    videos: list[dict] = []
    cursor = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    for _ in range(max_pages):
        r = requests.get(
            TIKWM_USER_POSTS,
            params={"unique_id": username, "count": 30, "cursor": cursor},
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"tikwm: {payload.get('msg') or payload}")
        data = payload.get("data") or {}
        batch = data.get("videos") or []
        if not batch:
            break
        videos.extend(batch)
        if not data.get("hasMore"):
            break
        cursor = int(data.get("cursor") or 0)
        time.sleep(0.4)
    return videos


def filter_videos_yesterday(videos: list[dict]) -> list[dict]:
    start, end = _yesterday_vn_range()
    out = []
    for v in videos:
        ts = int(v.get("create_time") or 0)
        if start <= ts < end:
            out.append(v)
    return out


def _yesterday_video_limit(cfg: dict | None) -> int:
    if not cfg:
        return 0
    try:
        return max(0, int(cfg.get("yesterdayVideoCount") or 0))
    except (TypeError, ValueError):
        return 0


def apply_yesterday_video_limit(videos: list[dict], cfg: dict | None) -> list[dict]:
    """Giới hạn số video hôm qua (0 = tất cả). Ưu tiên video mới hơn trong ngày."""
    if not videos:
        return videos
    limit = _yesterday_video_limit(cfg)
    ordered = sorted(videos, key=lambda v: int(v.get("create_time") or 0), reverse=True)
    if limit > 0:
        return ordered[:limit]
    return ordered


def download_file(url: str, dest: str, *, referer: str = "https://www.tiktok.com/") -> str:
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with requests.get(url, stream=True, timeout=600, headers={"Referer": referer}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def download_video(url: str, dest: str) -> str:
    return download_file(url, dest, referer="https://www.tiktok.com/")


def extract_frame_at_sec(video_path: str, out_image: str, sec: float = 1.0) -> str:
    out_image = os.path.abspath(out_image)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(sec), "-i", video_path,
        "-frames:v", "1", "-q:v", "2", out_image,
    ]
    subprocess.run(cmd, check=True, timeout=120)
    if not os.path.isfile(out_image) or os.path.getsize(out_image) < 100:
        raise RuntimeError("frame_extract_failed")
    return out_image


def _wardrobe_replace_mode(cfg: dict | None = None) -> str:
    """Luôn thay nguyên bộ (full outfit) — không chỉ áo hoặc quần riêng lẻ."""
    if cfg:
        mode = (cfg.get("wardrobeReplace") or "").strip().lower()
        if mode in ("full", "upper", "lower"):
            return mode
    return "full"


def _frame_seconds(cfg: dict | None = None) -> list[float]:
    """Ưu tiên frame muộn hơn để bắt cả áo + quần/váy (tránh chỉ thấy áo)."""
    base = 2.5
    if cfg:
        try:
            base = float(cfg.get("frameSec") or base)
        except (TypeError, ValueError):
            pass
    candidates = [base, base + 1.0, max(1.0, base - 0.5), 3.5]
    seen: set[float] = set()
    out: list[float] = []
    for s in candidates:
        k = round(s, 2)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def run_wardrobe_vae(
    client: VideoAiEasyClient,
    template_url: str,
    clothes_path: str,
    *,
    tmp: str,
    wardrobe_replace: str = "full",
) -> str:
    template_path = os.path.join(tmp, "batch_template.png")
    download_file(template_url, template_path, referer="https://kaling.cloud/")
    print(f"👗 Thay đồ VAE (wardrobe_replace={wardrobe_replace})...")
    person_url = client.upload_file(template_path, kind="image")
    clothes_url = client.upload_file(clothes_path, kind="image")
    job_id = client.create_wardrobe_job(
        person_image_url=person_url,
        clothes_image_url=clothes_url,
        wardrobe_replace=wardrobe_replace,
    )
    job = poll_vae_job(client, job_id, label="wardrobe")
    out_url = normalize_vae_public_url(job.get("output_video_url"))
    if not out_url:
        raise RuntimeError("wardrobe no output url")
    return out_url


# ── MEO3 Wardrobe (api.meo3.cloud) ─────────────────────────────────────────
MEO3_API_BASE = "https://api.meo3.cloud"


def run_wardrobe_meo3(
    template_url: str,
    clothes_path: str,
    *,
    tmp: str,
    aspect_ratio: str = "1:1",
    poll_interval: float = 3.0,
    timeout_sec: float = 180.0,
) -> str:
    """Thay đồ qua API meo3.cloud — POST /api/try-on, rồi poll GET /api/tasks/{id}."""
    # 1. Tải ảnh người mẫu (template) về local
    template_path = os.path.join(tmp, "meo3_person.jpg")
    download_file(template_url, template_path, referer="https://kaling.cloud/")
    print(f"👗 Thay đồ Meo3 (aspect={aspect_ratio})...")

    # 2. Gửi yêu cầu thay đồ
    with open(template_path, "rb") as fp_person, open(clothes_path, "rb") as fp_clothes:
        resp = requests.post(
            f"{MEO3_API_BASE}/api/try-on",
            files={
                "personImage": ("person.jpg", fp_person, "image/jpeg"),
                "garmentImage": ("garment.jpg", fp_clothes, "image/jpeg"),
            },
            data={
                "preserve": "true",
                "aspectRatio": aspect_ratio,
                "model": "nano_banana_pro",
            },
            timeout=30,
        )
    if not resp.ok:
        raise RuntimeError(f"Meo3 try-on request failed: {resp.status_code} {resp.text[:200]}")
    task_id = resp.json().get("taskId")
    if not task_id:
        raise RuntimeError(f"Meo3 no taskId in response: {resp.text[:200]}")
    print(f"   Meo3 task: {task_id}")

    # 3. Poll trạng thái
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(poll_interval)
        status_resp = requests.get(f"{MEO3_API_BASE}/api/tasks/{task_id}", timeout=15)
        if not status_resp.ok:
            continue
        status_data = status_resp.json()
        status = status_data.get("status", "")
        print(f"   Meo3 status: {status}")
        if status == "completed":
            media_url = status_data.get("mediaUrl")
            if not media_url:
                raise RuntimeError("Meo3 completed but no mediaUrl")
            return media_url
        if status == "failed":
            raise RuntimeError(f"Meo3 task failed: {status_data.get('error', 'unknown')}")

    raise RuntimeError(f"Meo3 timeout sau {timeout_sec}s (task={task_id})")



def _batch_model_preset(cfg: dict) -> dict:
    key = (cfg.get("batchModelKey") or "vae10").strip().lower()
    preset = dict(BATCH_MODEL_PRESETS.get(key) or BATCH_MODEL_PRESETS["vae10"])
    if cfg.get("modelId"):
        preset["modelId"] = str(cfg.get("modelId"))
    if cfg.get("renderProvider"):
        preset["renderProvider"] = str(cfg.get("renderProvider"))
    if cfg.get("vaeDurationSec") is not None:
        preset["vaeDurationSec"] = int(cfg.get("vaeDurationSec"))
    if cfg.get("vaeResolution"):
        preset["vaeResolution"] = str(cfg.get("vaeResolution"))
    if cfg.get("maxVideoSec") is not None:
        preset["maxVideoSec"] = int(cfg.get("maxVideoSec"))
    if cfg.get("costCoins") is not None:
        preset["costCoins"] = float(cfg.get("costCoins"))
    if cfg.get("serviceLabel"):
        preset["serviceLabel"] = str(cfg.get("serviceLabel"))
    return preset


def _batch_cost_coins(cfg: dict) -> float:
    return float(_batch_model_preset(cfg).get("costCoins") or BATCH_ORDER_COST_COINS)


def create_batch_order(
    db,
    *,
    admin_uid: str,
    admin_email: str,
    admin_name: str,
    char_url: str,
    video_url: str,
    batch_run_id: str,
    source_video_id: str = "",
    source_order_id: str = "",
    model_preset: dict | None = None,
) -> str:
    model = dict(model_preset or BATCH_MODEL_PRESETS["vae10"])
    cost = float(model.get("costCoins") or BATCH_ORDER_COST_COINS)
    ref = db.collection("orders").document()
    payload = {
        "userId": admin_uid,
        "userEmail": admin_email or "",
        "userName": admin_name or "Admin",
        "packageName": "Xây kênh tự động",
        "modelId": str(model.get("modelId") or BATCH_MODEL_ID),
        "renderProvider": model.get("renderProvider") or BATCH_RENDER_PROVIDER,
        "vaeDurationSec": int(model.get("vaeDurationSec") or BATCH_VAE_DURATION_SEC),
        "vaeResolution": model.get("vaeResolution") or BATCH_VAE_RESOLUTION,
        "maxVideoSec": int(model.get("maxVideoSec") or BATCH_MAX_VIDEO_SEC),
        "clientVersion": APP_CLIENT_VERSION,
        "serviceType": "motion-to-char",
        "serviceLabel": model.get("serviceLabel") or "Kling 2.6 Pro (20s)",
        "costCoins": cost,
        "characterImageLink": char_url,
        "referenceVideoLink": video_url,
        "aspectRatio": "9:16",
        "status": "pending",
        "resultLink": "",
        "adminNote": "batch-channel",
        "isBatchChannel": True,
        "batchChannelRunId": batch_run_id,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if source_video_id:
        payload["batchSourceVideoId"] = source_video_id
    if source_order_id:
        payload["batchSourceOrderId"] = source_order_id
    ref.set(payload)
    return ref.id


def _deduct_user_coins(db, user_id: str, amount: float) -> None:
    amount = round(float(amount), 1)
    if amount <= 0:
        return
    if not user_id:
        raise InsufficientCoinsError(f"Không đủ coin: cần {amount}, có 0")
    user_ref = db.collection("users").document(user_id)

    @firestore.transactional
    def _deduct_tx(transaction):
        snap = user_ref.get(transaction=transaction)
        current = float((snap.to_dict() or {}).get("coins") or 0) if snap.exists else 0.0
        if current + 1e-9 < amount:
            raise InsufficientCoinsError(f"Không đủ coin: cần {amount}, có {current}")
        transaction.update(user_ref, {"coins": round(current - amount, 1)})

    _deduct_tx(db.transaction())
    print(f"💳 Trừ {amount} coin — user {user_id}")


def _refund_user_coins(db, user_id: str, amount: float) -> None:
    amount = round(float(amount), 1)
    if amount <= 0 or not user_id:
        return
    db.collection("users").document(user_id).update({"coins": firestore.Increment(amount)})
    print(f"💰 Hoàn {amount} coin cho user {user_id}")


def _sync_config_run_progress(
    cfg_ref,
    *,
    state: str,
    phase: str = "",
    videos_found: int | None = None,
    orders_created: int | None = None,
    errors: list[str] | None = None,
    run_id: str = "",
    last_message: str = "",
    last_status: str = "",
) -> None:
    upd: dict = {
        "activeRunStatus": state,
        "activeRunPhase": phase,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if run_id:
        upd["activeRunId"] = run_id
    if videos_found is not None:
        upd["activeRunVideosFound"] = int(videos_found)
    if orders_created is not None:
        upd["activeRunOrdersCreated"] = int(orders_created)
    if errors is not None:
        upd["activeRunErrors"] = list(errors)[-10:]
    if last_message:
        upd["lastRunMessage"] = last_message
    if last_status:
        upd["lastRunStatus"] = last_status
    if state in ("completed", "failed", "idle"):
        upd["activeRunPhase"] = phase
    cfg_ref.update(upd)


def _format_batch_summary(*, videos_found: int, orders_created: int, errors: list[str]) -> str:
    if orders_created <= 0 and errors:
        detail = errors[0]
        if len(errors) > 1:
            detail += f" (+{len(errors) - 1} lỗi khác)"
        return f"Thất bại — không tạo được đơn nào. {detail}"
    msg = f"Hoàn tất: đã tạo {orders_created} đơn hàng"
    if videos_found > 0:
        msg += f" từ {videos_found} video TikTok hôm qua"
    msg += ". Mỗi đơn sẽ render AI — xem tiến độ ở danh sách Video của tôi."
    if errors:
        msg += f" ({len(errors)} video lỗi: {'; '.join(errors[:2])}"
        if len(errors) > 2:
            msg += f" … +{len(errors) - 2}"
        msg += ")"
    return msg


def _process_video_item(
    vae_client: VideoAiEasyClient,
    db,
    *,
    cfg: dict,
    template_url: str,
    admin_uid: str,
    admin_email: str,
    admin_name: str,
    run_ref,
    video_url: str,
    item_key: str,
    source_video_id: str = "",
    source_order_id: str = "",
    referer: str = "https://www.tiktok.com/",
    cfg_ref=None,
    progress_label: str = "",
) -> dict:
    wardrobe_mode = _wardrobe_replace_mode(cfg)
    item = {"videoId": item_key, "status": "pending", "orderId": ""}
    if source_order_id:
        item["sourceOrderId"] = source_order_id
    if cfg_ref is not None and progress_label:
        _sync_config_run_progress(
            cfg_ref,
            state="running",
            phase=f"{progress_label}: đang tải video & cắt khung hình…",
        )
    with tempfile.TemporaryDirectory(prefix="batch_ch_") as tmp:
        video_local = os.path.join(tmp, f"{item_key}.mp4")
        print(f"▶️ Nguồn {item_key}...")
        download_file(video_url, video_local, referer=referer)
        frame_local = _extract_outfit_frame(video_local, tmp, item_key, cfg)
        model_preset = _batch_model_preset(cfg)
        cost_coins = _batch_cost_coins(cfg)
        coins_deducted = False
        if cfg_ref is not None and progress_label:
            _sync_config_run_progress(
                cfg_ref,
                state="running",
                phase=f"{progress_label}: đang thay đồ AI (VAE)…",
            )
        try:
            _deduct_user_coins(db, admin_uid, cost_coins)
            coins_deducted = True
            char_url = run_wardrobe_meo3(
                template_url, frame_local, tmp=tmp,
            )
            motion_url = upload_motion_video(video_local)
            order_id = create_batch_order(
                db,
                admin_uid=admin_uid,
                admin_email=admin_email,
                admin_name=admin_name,
                char_url=char_url,
                video_url=motion_url,
                batch_run_id=run_ref.id,
                source_video_id=source_video_id,
                source_order_id=source_order_id,
                model_preset=model_preset,
            )
        except Exception:
            if coins_deducted:
                _refund_user_coins(db, admin_uid, cost_coins)
            raise
        item["status"] = "order_created"
        item["orderId"] = order_id
        item["characterImageLink"] = char_url
        item["referenceVideoLink"] = motion_url
        print(f"   ✅ Đơn {order_id}")
    return item


def _extract_outfit_frame(video_path: str, tmp: str, vid_key: str, cfg: dict) -> str:
    last_err: Exception | None = None
    for sec in _frame_seconds(cfg):
        frame_local = os.path.join(tmp, f"{vid_key}_t{sec}.png")
        try:
            extract_frame_at_sec(video_path, frame_local, sec)
            print(f"   🖼️ Frame t={sec}s")
            return frame_local
        except Exception as e:
            last_err = e
    raise RuntimeError(f"frame_extract_failed: {last_err}")


def upload_motion_video(local_path: str) -> str:
    url = upload_result_file(local_path, folder="motions", content_type="video/mp4")
    if not url:
        raise RuntimeError("upload motion video failed")
    return url


def _firestore_ts_seconds(ts) -> float:
    if ts is None:
        return 0.0
    if hasattr(ts, "timestamp"):
        return float(ts.timestamp())
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _pending_run_now_configs(db) -> list[tuple[str, dict]]:
    pending: list[tuple[str, dict]] = []
    for snap in db.collection(CONFIG_COLLECTION).stream():
        if not snap.exists:
            continue
        cfg = snap.to_dict() or {}
        requested = cfg.get("runNowRequestedAt")
        if not requested:
            continue
        handled = cfg.get("runNowHandledAt")
        if _firestore_ts_seconds(handled) >= _firestore_ts_seconds(requested):
            continue
        pending.append((snap.id, cfg))
    return pending


def _trigger_config_run(db, config_id: str, cfg: dict) -> int:
    mode = (cfg.get("runNowMode") or "test").strip().lower()
    if (
        mode == "full"
        and (get_env("BATCH_RUN_NOW_USE_TEST") or "").strip().lower() in ("1", "true", "yes")
    ):
        print("🧪 BATCH_RUN_NOW_USE_TEST=1 — run now dùng 1 video mới nhất (local dev)")
        mode = "test"
    db.collection(CONFIG_COLLECTION).document(config_id).update({
        "runNowHandledAt": cfg.get("runNowRequestedAt"),
        "activeRunStatus": "running",
        "activeRunPhase": "Đang khởi động — lấy video TikTok…",
        "activeRunVideosFound": 0,
        "activeRunOrdersCreated": 0,
        "activeRunErrors": [],
    })
    order_ids = [str(x).strip() for x in (cfg.get("selectedOrderIds") or []) if str(x).strip()]
    owner = (cfg.get("createdBy") or config_id).strip() or config_id
    if mode == "orders":
        print(f"🚀 [{owner}] Làm ngay — {len(order_ids)} đơn nguồn.")
        return run_batch(
            force=True,
            manual=True,
            source_mode="orders",
            order_ids=order_ids,
            config_id=config_id,
        )
    if mode == "full":
        print(f"🚀 [{owner}] Làm ngay — batch video hôm qua.")
        return run_batch(force=True, manual=True, config_id=config_id)
    print(f"🚀 [{owner}] Chạy thử — 1 video.")
    return run_batch(force=True, test_latest=1, manual=True, config_id=config_id)


def _close_stale_running_runs(db, *, max_age_hours: int = STALE_RUNNING_RUN_HOURS) -> int:
    """Đóng batch zombie (status=running quá lâu) để không chặn hàng đợi."""
    cutoff_ts = time.time() - max_age_hours * 3600
    closed = 0
    for snap in db.collection(RUNS_COLLECTION).where("status", "==", "running").stream():
        data = snap.to_dict() or {}
        started_ts = _firestore_ts_seconds(data.get("startedAt"))
        if not started_ts or started_ts >= cutoff_ts:
            continue
        snap.reference.update({
            "status": "failed",
            "finishedAt": firestore.SERVER_TIMESTAMP,
            "errors": (data.get("errors") or []) + ["stale_run_auto_closed"],
            "lastError": f"Batch kẹt > {max_age_hours}h — đã đóng tự động",
        })
        closed += 1
        print(f"🧹 Đóng batch zombie {snap.id}")
    return closed


def poll_run_now_trigger() -> int:
    """Cron mỗi phút — chạy batch khi user bấm Chạy thử / Làm ngay trên web."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(ROOT / "serviceAccountKey.json"))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    _close_stale_running_runs(db)
    pending = _pending_run_now_configs(db)
    if not pending:
        return 0
    running = (
        db.collection(RUNS_COLLECTION)
        .where("status", "==", "running")
        .limit(1)
        .stream()
    )
    if any(True for _ in running):
        print("⏳ Batch đang chạy — bỏ qua trigger mới.")
        return 0
    rc = 0
    for config_id, cfg in pending:
        rc = max(rc, _trigger_config_run(db, config_id, cfg))
    return rc


def run_daily_hourly() -> int:
    """Cron mỗi giờ — chạy mọi user config đang bật đúng cronHour (VN)."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(ROOT / "serviceAccountKey.json"))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    now_hour = _vn_now().hour
    y_date = (_vn_now().date() - timedelta(days=1)).isoformat()
    rc = 0
    for snap in db.collection(CONFIG_COLLECTION).stream():
        if not snap.exists:
            continue
        cfg = snap.to_dict() or {}
        if not cfg.get("enabled"):
            continue
        try:
            cron_hour = int(cfg.get("cronHour") if cfg.get("cronHour") is not None else 3)
        except (TypeError, ValueError):
            cron_hour = 3
        cron_hour = max(0, min(23, cron_hour))
        if now_hour != cron_hour:
            continue
        if cfg.get("lastDailyCronDateVN") == y_date:
            continue
        owner = (cfg.get("createdBy") or snap.id).strip() or snap.id
        owner_email = (cfg.get("createdByEmail") or "").strip()
        if not _is_batch_channel_allowlisted(db, owner_email):
            print(f"⏭️ Batch kênh [{owner}] — email không trong allowlist, bỏ qua.")
            continue
        print(f"⏰ Cron batch kênh [{owner}] — {cron_hour}:00 VN, video {y_date}")
        one_rc = run_batch(force=False, manual=False, config_id=snap.id)
        rc = max(rc, one_rc)
        if one_rc == 0:
            snap.reference.update({"lastDailyCronDateVN": y_date})
    return rc


def run_batch(
    *,
    force: bool = False,
    test_latest: int | None = None,
    manual: bool = False,
    source_mode: str | None = None,
    order_ids: list[str] | None = None,
    config_id: str = CONFIG_DOC,
) -> int:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(ROOT / "serviceAccountKey.json"))
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    cfg_ref = db.collection(CONFIG_COLLECTION).document(config_id)
    cfg_snap = cfg_ref.get()
    if not cfg_snap.exists:
        print(f"⏭️ Chưa có batchChannelConfig/{config_id} — bỏ qua.")
        return 0
    cfg = cfg_snap.to_dict() or {}
    if not manual and not cfg.get("enabled"):
        print("⏭️ Batch kênh đang tắt (enabled=false).")
        return 0

    try:
        vae_client, _vae_acc = get_batch_vae_client()
    except (VideoAiEasyError, VideoAiEasyAuthError, RuntimeError) as e:
        print(f"❌ Không đăng nhập VAE: {e}")
        return 1

    template_url = (cfg.get("templateImageUrl") or "").strip()
    channel = (cfg.get("channelUsername") or cfg.get("channelUrl") or "").strip()
    admin_uid = (cfg.get("createdBy") or "").strip()
    admin_email = (cfg.get("createdByEmail") or "").strip()
    admin_name = (cfg.get("createdByName") or "Admin").strip()
    if not _is_batch_channel_allowlisted(db, admin_email):
        print(f"⏭️ Email {admin_email or admin_uid} không trong batchChannelAllowlist — bỏ qua.")
        return 0
    source_mode = (source_mode or cfg.get("sourceMode") or "tiktok").strip().lower()
    if not template_url or not admin_uid:
        print("❌ Config thiếu templateImageUrl / createdBy")
        return 1
    if source_mode != "orders" and not channel:
        print("❌ Config thiếu channel (chế độ TikTok)")
        return 1

    if test_latest and test_latest > 0:
        y_date = f"test-{_vn_now().date().isoformat()}"
    else:
        y_date = (_vn_now().date() - timedelta(days=1)).isoformat()
    if not force and not manual:
        recent = (
            db.collection(RUNS_COLLECTION)
            .where("dateVN", "==", y_date)
            .where("configId", "==", config_id)
            .where("status", "==", "completed")
            .limit(1)
            .stream()
        )
        if any(True for _ in recent):
            print(f"⏭️ Đã chạy batch cho ngày {y_date} (config {config_id}).")
            return 0

    username = parse_tiktok_username(channel) if channel else ""
    run_ref = db.collection(RUNS_COLLECTION).document()
    run_ref.set({
        "dateVN": y_date,
        "channelUsername": username,
        "sourceMode": source_mode,
        "status": "running",
        "isManualTest": bool(manual or test_latest),
        "testLatest": int(test_latest or 0),
        "yesterdayVideoCount": _yesterday_video_limit(cfg),
        "userId": admin_uid,
        "configId": config_id,
        "startedAt": firestore.SERVER_TIMESTAMP,
        "videosFound": 0,
        "ordersCreated": 0,
        "items": [],
        "errors": [],
    })

    errors: list[str] = []
    items: list[dict] = []
    orders_created = 0

    _sync_config_run_progress(
        cfg_ref,
        state="running",
        phase="Đang lấy danh sách video TikTok hôm qua…",
        videos_found=0,
        orders_created=0,
        errors=[],
        run_id=run_ref.id,
    )

    try:
        if source_mode == "orders":
            ids = order_ids if order_ids is not None else [
                str(x).strip() for x in (cfg.get("selectedOrderIds") or []) if str(x).strip()
            ]
            if not ids:
                raise RuntimeError("Chưa chọn đơn nguồn (selectedOrderIds)")
            print(f"📋 Copy {len(ids)} đơn có ảnh + video...")
            run_ref.update({"videosFound": len(ids)})
            for oid in ids:
                snap = db.collection("orders").document(oid).get()
                if not snap.exists:
                    errors.append(f"{oid}: not_found")
                    items.append({"videoId": oid, "status": "error", "error": "not_found", "orderId": ""})
                    run_ref.update({"items": items, "ordersCreated": orders_created, "errors": errors})
                    continue
                od = snap.to_dict() or {}
                if (od.get("userId") or "").strip() != admin_uid:
                    errors.append(f"{oid}: not_owner")
                    items.append({"videoId": oid, "status": "error", "error": "not_owner", "orderId": ""})
                    run_ref.update({"items": items, "ordersCreated": orders_created, "errors": errors})
                    continue
                video_url = (od.get("referenceVideoLink") or "").strip()
                if not video_url:
                    errors.append(f"{oid}: no_reference_video")
                    items.append({"videoId": oid, "status": "error", "error": "no_reference_video", "orderId": ""})
                    run_ref.update({"items": items, "ordersCreated": orders_created, "errors": errors})
                    continue
                try:
                    item = _process_video_item(
                        vae_client, db,
                        cfg=cfg,
                        template_url=template_url,
                        admin_uid=admin_uid,
                        admin_email=admin_email,
                        admin_name=admin_name,
                        run_ref=run_ref,
                        video_url=video_url,
                        item_key=oid[-8:],
                        source_order_id=oid,
                        referer="https://kaling.cloud/",
                    )
                    orders_created += 1
                except Exception as e:
                    msg = f"{oid}: {e}"
                    print(f"   ❌ {msg}")
                    errors.append(msg)
                    item = {"videoId": oid, "sourceOrderId": oid, "status": "error", "error": str(e), "orderId": ""}
                items.append(item)
                run_ref.update({"items": items, "ordersCreated": orders_created, "errors": errors})
        else:
            if test_latest and test_latest > 0:
                print(f"📡 Lấy {test_latest} video mới nhất @{username} (chạy thử)...")
                all_videos = fetch_channel_videos(username)
                videos = all_videos[:test_latest]
                print(f"   Chọn {len(videos)} video (trong {len(all_videos)} gần nhất).")
            else:
                print(f"📡 Lấy video @{username} — ngày hôm qua VN ({y_date})...")
                all_videos = fetch_channel_videos(username)
                yesterday_all = filter_videos_yesterday(all_videos)
                videos = apply_yesterday_video_limit(yesterday_all, cfg)
                limit = _yesterday_video_limit(cfg)
                if limit > 0:
                    print(
                        f"   Chọn {len(videos)}/{len(yesterday_all)} video hôm qua "
                        f"(giới hạn {limit}, trong {len(all_videos)} gần nhất)."
                    )
                else:
                    print(f"   Tìm thấy {len(videos)} video hôm qua (trong {len(all_videos)} gần nhất).")
            run_ref.update({"videosFound": len(videos)})
            _sync_config_run_progress(
                cfg_ref,
                state="running",
                phase=f"Đã tìm {len(videos)} video — bắt đầu thay đồ & tạo đơn (mỗi video = 1 đơn)…",
                videos_found=len(videos),
                orders_created=0,
                errors=errors,
                run_id=run_ref.id,
            )
            if len(videos) == 0:
                errors.append("Không có video TikTok nào đăng hôm qua trên kênh này.")

            for idx, v in enumerate(videos, start=1):
                vid = str(v.get("video_id") or "")
                play = v.get("hdplay") or v.get("play") or ""
                if not vid or not play:
                    err = f"Video {vid or '?'}: không có link tải"
                    errors.append(err)
                    _sync_config_run_progress(
                        cfg_ref, state="running", videos_found=len(videos),
                        orders_created=orders_created, errors=errors,
                        phase=f"Video {idx}/{len(videos)}: bỏ qua (lỗi link)",
                    )
                    continue
                progress = f"Video {idx}/{len(videos)}"
                try:
                    item = _process_video_item(
                        vae_client, db,
                        cfg=cfg,
                        template_url=template_url,
                        admin_uid=admin_uid,
                        admin_email=admin_email,
                        admin_name=admin_name,
                        run_ref=run_ref,
                        video_url=play,
                        item_key=vid,
                        source_video_id=vid,
                        cfg_ref=cfg_ref,
                        progress_label=progress,
                    )
                    orders_created += 1
                    _sync_config_run_progress(
                        cfg_ref, state="running", videos_found=len(videos),
                        orders_created=orders_created, errors=errors,
                        phase=f"{progress}: đã tạo đơn #{orders_created}",
                    )
                except Exception as e:
                    msg = f"{progress}: {e}"
                    print(f"   ❌ {msg}")
                    errors.append(msg)
                    item = {"videoId": vid, "status": "error", "error": str(e), "orderId": ""}
                    _sync_config_run_progress(
                        cfg_ref, state="running", videos_found=len(videos),
                        orders_created=orders_created, errors=errors,
                        phase=f"{progress}: lỗi — {e}",
                    )
                items.append(item)
                run_ref.update({"items": items, "ordersCreated": orders_created, "errors": errors})

        run_snap = run_ref.get()
        vf = int((run_snap.to_dict() or {}).get("videosFound") or 0) if run_snap.exists else 0
        summary = _format_batch_summary(videos_found=vf, orders_created=orders_created, errors=errors)
        final_status = "failed" if orders_created <= 0 and errors else "completed"

        run_ref.update({
            "status": final_status,
            "finishedAt": firestore.SERVER_TIMESTAMP,
            "ordersCreated": orders_created,
            "errors": errors,
            "items": items,
        })
        _sync_config_run_progress(
            cfg_ref,
            state=final_status,
            phase=summary,
            videos_found=vf,
            orders_created=orders_created,
            errors=errors,
            last_message=summary,
            last_status=final_status,
        )
        cfg_ref.update({
            "lastRunAt": firestore.SERVER_TIMESTAMP,
            "lastRunStatus": final_status,
            "lastRunMessage": summary,
        })
        if final_status == "failed":
            print(f"❌ Batch thất bại: {summary}")
        else:
            print(f"✅ Batch xong: {summary}")
        return 0 if final_status == "completed" else 1
    except Exception as e:
        print(f"❌ Batch thất bại: {e}")
        err_msg = str(e)
        all_errors = errors + [err_msg]
        run_snap = run_ref.get()
        vf = int((run_snap.to_dict() or {}).get("videosFound") or 0) if run_snap.exists else 0
        summary = _format_batch_summary(videos_found=vf, orders_created=orders_created, errors=all_errors)
        run_ref.update({
            "status": "failed",
            "finishedAt": firestore.SERVER_TIMESTAMP,
            "errors": all_errors,
            "ordersCreated": orders_created,
            "items": items,
        })
        _sync_config_run_progress(
            cfg_ref,
            state="failed",
            phase=summary,
            videos_found=vf,
            orders_created=orders_created,
            errors=all_errors,
            last_message=summary,
            last_status="failed",
        )
        cfg_ref.update({
            "lastRunAt": firestore.SERVER_TIMESTAMP,
            "lastRunStatus": "failed",
            "lastRunMessage": summary,
        })
        return 1


def main():
    parser = argparse.ArgumentParser(description="Kaling — batch kênh TikTok")
    parser.add_argument("--force", action="store_true", help="Chạy lại dù đã có run completed hôm qua")
    parser.add_argument(
        "--test-latest",
        type=int,
        default=0,
        metavar="N",
        help="Chạy thử: lấy N video mới nhất thay vì chỉ hôm qua",
    )
    parser.add_argument(
        "--poll-trigger",
        action="store_true",
        help="Kiểm tra runNowRequestedAt trên Firestore (cron mỗi phút)",
    )
    parser.add_argument(
        "--daily-hourly",
        action="store_true",
        help="Cron mỗi giờ — chạy khi đúng cronHour trong batchChannelConfig",
    )
    args = parser.parse_args()
    if args.poll_trigger:
        sys.exit(poll_run_now_trigger())
    if args.daily_hourly:
        sys.exit(run_daily_hourly())
    test_latest = args.test_latest if args.test_latest > 0 else None
    sys.exit(run_batch(force=args.force or bool(test_latest), test_latest=test_latest))


if __name__ == "__main__":
    main()
