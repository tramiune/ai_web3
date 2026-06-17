"""
Kling chính chủ — Motion Control 2.6 / 720p / Matches Video.
Bot Kaling chỉ dùng engine này (nhánh bot_kling).
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from firebase_admin import firestore
from playwright.sync_api import sync_playwright

from kling_session import (
    KlingNetworkSniffer,
    KLING_DEFAULT_MODEL,
    KLING_DEFAULT_ORIENTATION,
    launch_kling_context,
    motion_file_inputs,
    open_motion_control,
    profile_dir_for_account,
    set_model_version,
    set_orientation,
    set_resolution,
    wait_for_login,
    wait_for_motion_ui,
)
from kling_pricing import KLING_MAX_VIDEO_SEC, billable_seconds
from project_env import get_env, load_project_env
from tool98_api import Tool98ApiError, probe_video_duration_seconds, trim_video_to_seconds
from user_order_notes import USER_NOTE_FILES_MISSING, USER_NOTE_SUBMIT_FAILED, user_note_for_render_failure

load_project_env()

RENDER_PROVIDER_KLING = "kling"
PROJECT_DIR = Path(__file__).resolve().parent
TMP_DIR = PROJECT_DIR / "tmp_kling"

TASK_ID_KEYS = (
    "taskId", "task_id", "workId", "work_id",
    "generationId", "generation_id", "id", "bizId", "biz_id",
)
VIDEO_URL_KEYS = (
    "videoUrl", "video_url", "downloadUrl", "download_url",
    "url", "resource", "mp4Url", "mp4_url",
)

_g: dict = {}
_accounts_cache: list[dict] | None = None
_accounts_cache_lock = threading.Lock()
_inflight: dict[str, int] = {}
_inflight_lock = threading.Lock()
KLING_MAX_CONCURRENT_PER_ACCOUNT = int(get_env("KLING_MAX_CONCURRENT", "1"))


def wire(**kwargs):
    _g.update(kwargs)


def enabled_for_bot(bot_name: str | None) -> bool:
    return bool(bot_name and "kling" in (bot_name or "").lower())


def _print(msg: str) -> None:
    fn = _g.get("print")
    if fn:
        fn(msg)
    else:
        print(msg)


def _submit_lock():
    return _g.get("browser_lock")


def _inflight_inc(account_id: str) -> None:
    with _inflight_lock:
        _inflight[account_id] = _inflight.get(account_id, 0) + 1


def _inflight_dec(account_id: str) -> None:
    with _inflight_lock:
        cur = _inflight.get(account_id, 0) - 1
        if cur <= 0:
            _inflight.pop(account_id, None)
        else:
            _inflight[account_id] = cur


def _account_id(nick: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", (nick or "").strip().lower()).strip("_") or "default"


def load_kling_accounts() -> list[dict]:
    global _accounts_cache
    with _accounts_cache_lock:
        if _accounts_cache is not None:
            return _accounts_cache

        accounts: list[dict] = []
        path_map: dict[str, str] = {}
        raw_paths = (get_env("KLING_ACCOUNT_PATHS") or "").strip()
        if raw_paths:
            for part in raw_paths.split(","):
                part = part.strip()
                if ":" not in part:
                    continue
                nick, path = part.split(":", 1)
                nick = nick.strip()
                path = path.strip()
                if nick and path:
                    path_map[_account_id(nick)] = path

        raw = (get_env("KLING_ACCOUNTS") or get_env("KLING_PROFILES") or "").strip()
        nicks = [n.strip() for n in raw.split(",") if n.strip()] if raw else []
        if not nicks:
            nicks = ["default"]

        for nick in nicks:
            aid = _account_id(nick)
            profile = path_map.get(aid) or str(profile_dir_for_account(aid))
            accounts.append({
                "id": aid,
                "nick": nick,
                "profile_path": profile,
            })

        _accounts_cache = accounts
        return accounts


def _pick_kling_account() -> dict | None:
    accounts = load_kling_accounts()
    if not accounts:
        return None
    candidates = []
    for acc in accounts:
        aid = acc["id"]
        with _inflight_lock:
            load = _inflight.get(aid, 0)
        if load >= KLING_MAX_CONCURRENT_PER_ACCOUNT:
            continue
        candidates.append((load, aid, acc))
    if not candidates:
        candidates = [(0, acc["id"], acc) for acc in accounts]
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def log_accounts_on_startup() -> None:
    accounts = load_kling_accounts()
    _print(f"✅ Kling: {len(accounts)} profile(s)")
    for acc in accounts:
        _print(f"   · {acc['nick']} → {acc['profile_path']}")


def _extract_task_id(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key in TASK_ID_KEYS:
            val = payload.get(key)
            if val is not None and str(val).strip():
                s = str(val).strip()
                if s.isdigit() or len(s) >= 8:
                    return s
        for val in payload.values():
            found = _extract_task_id(val)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_task_id(item)
            if found:
                return found
    return None


def _extract_video_url(payload: object) -> str | None:
    if isinstance(payload, str):
        if payload.startswith("http") and (
            any(payload.lower().endswith(ext) for ext in (".mp4", ".mov", ".webm"))
            or "video" in payload.lower()
        ):
            return payload
        return None
    if isinstance(payload, dict):
        for key in VIDEO_URL_KEYS:
            val = payload.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        for val in payload.values():
            found = _extract_video_url(val)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_video_url(item)
            if found:
                return found
    return None


def _normalize_media_url(url: str) -> str:
    return (url or "").strip().split("?")[0].rstrip("/")


def _is_input_or_preview_url(url: str, ignore: set[str]) -> bool:
    norm = _normalize_media_url(url)
    if not norm:
        return True
    if norm in ignore:
        return True
    low = norm.lower()
    if "motionai-upload-api" in low:
        return True
    if low.startswith("blob:"):
        return True
    return False


def _snapshot_page_media_urls(page) -> set[str]:
    urls: set[str] = set()
    try:
        videos = page.locator("video[src^='http']")
        for i in range(videos.count()):
            src = videos.nth(i).get_attribute("src")
            if src and src.startswith("http"):
                urls.add(_normalize_media_url(src))
    except Exception:
        pass
    try:
        links = page.locator("a[href*='.mp4'], a[download]")
        for i in range(links.count()):
            href = links.nth(i).get_attribute("href")
            if href and href.startswith("http"):
                urls.add(_normalize_media_url(href))
    except Exception:
        pass
    return urls


def _urls_from_sniffer(sniffer: KlingNetworkSniffer, start_index: int = 0) -> set[str]:
    urls: set[str] = set()
    for ev in sniffer.events[start_index:]:
        url = _extract_video_url(ev.body)
        if url:
            urls.add(_normalize_media_url(url))
    return urls


def _video_url_from_sniffer(
    sniffer: KlingNetworkSniffer,
    *,
    start_index: int = 0,
    ignore: set[str] | None = None,
) -> str | None:
    ignore = ignore or set()
    preferred: str | None = None
    fallback: str | None = None
    for ev in reversed(sniffer.events[start_index:]):
        if ev.status >= 400:
            continue
        url = _extract_video_url(ev.body)
        if not url or _is_input_or_preview_url(url, ignore):
            continue
        ev_low = (ev.url or "").lower()
        if any(
            token in ev_low
            for token in ("result", "history", "task", "work", "generation", "output", "download")
        ):
            return url
        if not fallback:
            fallback = url
    return preferred or fallback


def _task_id_from_sniffer(sniffer: KlingNetworkSniffer, start_index: int = 0) -> str | None:
    for ev in reversed(sniffer.events[start_index:]):
        if ev.method not in ("POST", "PUT", "PATCH") or ev.status >= 400:
            continue
        if not isinstance(ev.body, dict):
            continue
        task_id = _extract_task_id(ev.body)
        if task_id:
            return task_id
    return None


def _prepare_motion_video(video_path: Path) -> tuple[Path, Path | None]:
    max_sec = float(get_env("KLING_MAX_VIDEO_SEC", str(KLING_MAX_VIDEO_SEC)))
    dur = probe_video_duration_seconds(str(video_path))
    if dur is not None and dur <= max_sec + 0.15:
        bill = billable_seconds(dur)
        _print(f"Video {dur:.1f}s — tính phí {bill}s (≤ {max_sec}s)")
        return video_path, None
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out = TMP_DIR / f"trim_{int(time.time())}_{video_path.name}"
        trim_video_to_seconds(video_path, max_seconds=max_sec, output=out)
        _print(f"✂️ Cắt video {dur or '?'}s → {max_sec}s")
        return out, out
    except Tool98ApiError as exc:
        _print(f"⚠️ Không cắt được video ({exc}) — dùng file gốc")
        return video_path, None


def _upload_motion_files(page, image_path: Path, video_path: Path) -> None:
    inputs = motion_file_inputs(page)
    _print(f"Upload video: {video_path.name}")
    inputs.nth(0).set_input_files(str(video_path))
    page.wait_for_timeout(2000)
    _print(f"Upload ảnh: {image_path.name}")
    inputs.nth(1).set_input_files(str(image_path))
    page.wait_for_timeout(2500)


def _click_generate(page) -> None:
    btn = page.get_by_role("button", name=re.compile(r"^Generate$", re.I))
    btn.first.wait_for(state="visible", timeout=30_000)
    btn.first.click()
    _print("Đã bấm Generate")


_SUBMIT_OK_TEXT = re.compile(
    r"generat|process|queue|queued|submitted|rendering|in progress|\d+\s*%",
    re.I,
)


def _submit_failure_from_sniffer(
    sniffer: KlingNetworkSniffer,
    start_index: int,
) -> str | None:
    for ev in reversed(sniffer.events[start_index:]):
        if ev.method not in ("POST", "PUT", "PATCH"):
            continue
        ev_low = (ev.url or "").lower()
        if not any(t in ev_low for t in ("generate", "motion", "task", "work", "submit")):
            continue
        if ev.status < 400:
            continue
        detail = ""
        if isinstance(ev.body, dict):
            for key in ("message", "msg", "error", "detail", "reason"):
                val = ev.body.get(key)
                if val:
                    detail = str(val)[:200]
                    break
        return detail or f"HTTP {ev.status} — {ev.url[:120]}"
    return None


def _submit_success_from_sniffer(
    sniffer: KlingNetworkSniffer,
    start_index: int,
) -> tuple[str | None, str | None]:
    """Trả về (task_id, log_line) nếu thấy job đã gửi thành công."""
    for ev in sniffer.events[start_index:]:
        if ev.method not in ("POST", "PUT", "PATCH"):
            continue
        ev_low = (ev.url or "").lower()
        if not any(t in ev_low for t in ("generate", "motion", "task", "work", "submit")):
            continue
        if ev.status >= 400:
            continue
        task_id = _extract_task_id(ev.body) if isinstance(ev.body, dict) else None
        if task_id:
            return task_id, f"API task id: {task_id}"
        if isinstance(ev.body, dict):
            code = ev.body.get("code")
            status = str(ev.body.get("status") or "").lower()
            if code in (0, "0", 200, "200") or status in ("success", "ok", "processing", "queued"):
                return None, f"API {ev.method} {ev.status} OK"
        if ev.status < 300:
            return None, f"API {ev.method} {ev.status} — {ev.url[:80]}"
    return None, None


def _ui_shows_generating(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000)
        if _SUBMIT_OK_TEXT.search(body):
            return True
    except Exception:
        pass
    try:
        btn = page.get_by_role("button", name=re.compile(r"^Generate$", re.I)).first
        if btn.count() > 0 and btn.is_disabled():
            return True
    except Exception:
        pass
    return False


def _wait_for_generate_success(
    page,
    sniffer: KlingNetworkSniffer,
    sniffer_start: int,
    *,
    timeout_sec: int | None = None,
) -> str | None:
    """Chờ tín hiệu Generate đã gửi job — raise nếu API lỗi hoặc hết giờ."""
    timeout = timeout_sec or int(get_env("KLING_SUBMIT_CONFIRM_SEC", "90"))
    deadline = time.time() + timeout
    _print(f"⏳ Chờ xác nhận Generate đã gửi (tối đa {timeout}s)...")
    while time.time() < deadline:
        fail = _submit_failure_from_sniffer(sniffer, sniffer_start)
        if fail:
            raise RuntimeError(f"Generate thất bại — {fail}")

        task_id, ok_line = _submit_success_from_sniffer(sniffer, sniffer_start)
        if ok_line:
            _print(f"✅ Generate OK — {ok_line}")
            return task_id

        if _ui_shows_generating(page):
            _print("✅ Generate OK — trang đang Generating/Processing")
            return None

        page.wait_for_timeout(2000)

    raise TimeoutError(
        "Không xác nhận được Generate — có thể chưa gửi job "
        "(thiếu credit Kling, upload lỗi, hoặc nút chưa bấm được)"
    )


def _sleep_until_min_render(generate_clicked_at: float, min_render_sec: int, poll_sec: int) -> None:
    """Chờ đủ min_render_sec trước khi poll kết quả; log mỗi poll_sec."""
    while True:
        waited = int(time.time() - generate_clicked_at)
        if waited >= min_render_sec:
            _print(f"⏳ Đủ {min_render_sec}s — bắt đầu poll kết quả mỗi {poll_sec}s")
            return
        remaining = min_render_sec - waited
        step = min(poll_sec, remaining)
        _print(f"⏳ Chờ Kling render ({waited}/{min_render_sec}s) — chưa poll kết quả")
        time.sleep(step)


def _poll_on_page(
    page,
    sniffer: KlingNetworkSniffer,
    timeout_sec: int,
    *,
    ignore_urls: set[str] | None = None,
    sniffer_start_index: int = 0,
    generate_clicked_at: float | None = None,
    min_render_sec: int | None = None,
) -> str | None:
    ignore = set(ignore_urls or set())
    min_render = min_render_sec
    if min_render is None:
        min_render = int(get_env("KLING_MIN_RENDER_SEC", get_env("BOT_MIN_RENDER_SEC", "120")))
    poll_sec = int(get_env("KLING_POLL_SEC", "30"))
    if generate_clicked_at is not None:
        _sleep_until_min_render(generate_clicked_at, min_render, poll_sec)
    deadline = time.time() + timeout_sec
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        video_url = _video_url_from_sniffer(
            sniffer,
            start_index=sniffer_start_index,
            ignore=ignore,
        )
        if video_url:
            waited = int(time.time() - (generate_clicked_at or time.time()))
            _print(f"Kết quả từ API sau {waited}s")
            return video_url

        try:
            videos = page.locator("video[src^='http']")
            for i in range(videos.count()):
                src = videos.nth(i).get_attribute("src")
                if src and src.startswith("http") and not _is_input_or_preview_url(src, ignore):
                    waited = int(time.time() - (generate_clicked_at or time.time()))
                    _print(f"Thấy video kết quả mới sau {waited}s (poll #{attempt})")
                    return src
        except Exception:
            pass

        try:
            links = page.locator("a[href*='.mp4'], a[download]")
            for i in range(links.count()):
                href = links.nth(i).get_attribute("href")
                if href and href.startswith("http") and not _is_input_or_preview_url(href, ignore):
                    waited = int(time.time() - (generate_clicked_at or time.time()))
                    _print(f"Thấy link tải kết quả sau {waited}s (poll #{attempt})")
                    return href
        except Exception:
            pass

        _print(f"Poll #{attempt} — chưa có video kết quả...")
        time.sleep(poll_sec)
        try:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    return None


def _download_result(url: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    _print(f"Tải kết quả → {output}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with output.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    return output


def _orientation_for_order(order_data: dict) -> str:
    raw = (order_data.get("klingOrientation") or get_env("KLING_CHARACTER_ORIENTATION", KLING_DEFAULT_ORIENTATION))
    return str(raw).strip().lower() or "video"


def _run_kling_job(
    image_path: Path,
    video_path: Path,
    account: dict,
    *,
    orientation: str,
) -> Path:
    upload_video, trim_tmp = _prepare_motion_video(video_path)
    sniffer = KlingNetworkSniffer()
    out_path = TMP_DIR / f"result_{int(time.time())}.mp4"
    try:
        profile = Path(account["profile_path"])
        with sync_playwright() as p:
            context = launch_kling_context(p, profile_path=profile)
            page = context.pages[0] if context.pages else context.new_page()
            sniffer.attach(page)
            open_motion_control(page)
            wait_for_login(page, timeout_sec=int(get_env("KLING_LOGIN_TIMEOUT_SEC", "300")))
            wait_for_motion_ui(page)
            set_model_version(page, get_env("KLING_MODEL_VERSION", KLING_DEFAULT_MODEL))
            set_orientation(page, orientation)
            set_resolution(page, "720p")
            ignore_urls = _snapshot_page_media_urls(page) | _urls_from_sniffer(sniffer)
            sniffer_start = len(sniffer.events)
            _upload_motion_files(page, image_path, upload_video)
            ignore_urls |= _snapshot_page_media_urls(page) | _urls_from_sniffer(sniffer, sniffer_start)
            sniffer_start = len(sniffer.events)
            _click_generate(page)
            generate_clicked_at = time.time()
            task_id = _wait_for_generate_success(page, sniffer, sniffer_start)
            timeout_sec = int(get_env("KLING_POLL_TIMEOUT_SEC", "900"))
            video_url = _poll_on_page(
                page,
                sniffer,
                timeout_sec,
                ignore_urls=ignore_urls,
                sniffer_start_index=sniffer_start,
                generate_clicked_at=generate_clicked_at,
            )
            if not video_url:
                raise TimeoutError("Hết thời gian chờ Kling render")
            _download_result(video_url, out_path)
            context.close()
        return out_path
    finally:
        if trim_tmp and trim_tmp.exists() and trim_tmp != video_path:
            trim_tmp.unlink(missing_ok=True)


def _mark_order_processing(doc_ref, account: dict, task_id: str | None = None) -> None:
    payload = {
        "status": "processing",
        "renderProvider": RENDER_PROVIDER_KLING,
        "klingAccount": account["id"],
        "klingAccountNick": account.get("nick") or account["id"],
        "submittedAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if task_id:
        payload["klingTaskId"] = str(task_id)
    doc_ref.update(payload)


def _fail_order(doc, order_data, err_detail: str, system_note: str, context: str) -> None:
    notify = _g.get("notify_internal_error_telegram")
    if notify:
        notify(doc.id, order_data, err_detail, context)
    db = _g["db"]
    cost = order_data.get("costCoins", 0)
    user_id = order_data.get("userId")
    if cost > 0 and user_id:
        try:
            db.collection("users").document(user_id).update({"coins": firestore.Increment(cost)})
            _print(f"💰 Hoàn {cost} coin cho user {user_id}")
        except Exception as exc:
            _print(f"⚠️ Hoàn coin lỗi: {exc}")
    db.collection("orders").document(doc.id).update({
        "status": "failed",
        "adminNote": firestore.DELETE_FIELD,
        "systemNote": system_note,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    pop = _g.get("pop_processing_cache")
    if pop:
        pop(doc.id)


def submit_order(order_id: str) -> None:
    """Nạp đơn pending → Kling Motion Control (full flow)."""
    if not _g.get("is_bot_enabled")():
        _print(f"⏸️ Bot TẮT — bỏ qua {order_id}")
        return
    if _g.get("pending_submit_backoff_active")(order_id):
        return

    submitting_lock = _g["submitting_orders_lock"]
    submitting = _g["submitting_orders"]
    with submitting_lock:
        if order_id in submitting:
            _print(f"⏭️ Đơn {order_id} đang nạp — bỏ qua trùng")
            return
        submitting.add(order_id)

    char_path = None
    vid_path = None
    result_path = None
    account = None

    try:
        account = _pick_kling_account()
        if not account:
            raise RuntimeError("Chưa cấu hình KLING_ACCOUNTS")

        db = _g["db"]
        doc_ref = db.collection("orders").document(order_id)
        doc = doc_ref.get()
        if not doc.exists:
            return
        data = doc.to_dict() or {}
        if data.get("status") != "pending":
            return

        _print(f"\n⚡ [Kling 2.6 / 720p] {order_id} — nick {account['nick']}...")
        img_url = (data.get("characterImageLink") or "").strip()
        vid_url = (data.get("referenceVideoLink") or "").strip()
        if not img_url or not vid_url:
            _fail_order(doc, data, "Thiếu link ảnh/video", USER_NOTE_FILES_MISSING, "submit kling")
            return

        download = _g["download_file"]
        for attempt in range(1, 3):
            if attempt > 1:
                _print(f"🔄 Tải lại lần {attempt}...")
            char_path = download(img_url, f"char_{order_id}.png", referer="https://kling.ai/")
            vid_path = download(vid_url, f"vid_{order_id}.mp4", referer="https://kling.ai/")
            if char_path and vid_path:
                break
            time.sleep(2)

        if not char_path or not vid_path:
            _fail_order(doc, data, "Không tải được ảnh/video", USER_NOTE_FILES_MISSING, "submit kling")
            return

        _mark_order_processing(doc_ref, account)
        _inflight_inc(account["id"])

        orientation = _orientation_for_order(data)
        lock = _submit_lock()
        with lock:
            result_path = _run_kling_job(
                Path(char_path),
                Path(vid_path),
                account,
                orientation=orientation,
            )

        complete = _g.get("complete_order_with_video")
        if complete and complete(doc, str(result_path)):
            _print(f"✅ Đơn {order_id} hoàn tất (Kling)")
            try:
                short_id = order_id[-6:].upper()
                send = _g.get("send_telegram_message")
                if send:
                    send(
                        f"✅ <b>HOÀN TẤT</b> (Kling)\n"
                        f"🆔 #{short_id}\n"
                        f"👤 Nick: {account['nick']}"
                    )
            except Exception:
                pass
        else:
            raise RuntimeError("Không upload được kết quả lên R2")

    except Exception as exc:
        _print(f"❌ Kling thất bại {order_id}: {exc}")
        try:
            doc = _g["db"].collection("orders").document(order_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                if data.get("status") != "completed":
                    note = user_note_for_render_failure(str(exc))
                    _fail_order(doc, data, str(exc), note or USER_NOTE_SUBMIT_FAILED, "render kling")
        except Exception as inner:
            _print(f"⚠️ Không cập nhật fail {order_id}: {inner}")
        backoff = _g.get("session_error_backoff")
        if backoff is not None:
            backoff[order_id] = time.time() + int(get_env("SESSION_ERROR_BACKOFF_SEC", "300"))
    finally:
        if account:
            _inflight_dec(account["id"])
        for p in (char_path, vid_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if result_path and Path(result_path).exists():
            try:
                os.remove(result_path)
            except OSError:
                pass
        with submitting_lock:
            submitting.discard(order_id)


def poll_kling_orders(orders_to_check) -> None:
    """Poll đơn processing còn sót (browser crash giữa chừng)."""
    skip_done = _g.get("skip_if_order_done")
    min_render = int(get_env("KLING_MIN_RENDER_SEC", get_env("BOT_MIN_RENDER_SEC", "180")))
    now = datetime.now(timezone.utc)

    for doc in orders_to_check:
        data = doc.to_dict() or {}
        if data.get("renderProvider") != RENDER_PROVIDER_KLING:
            continue
        submitted = data.get("submittedAt")
        if submitted and (now - submitted).total_seconds() < min_render:
            continue

        account_id = (data.get("klingAccount") or "").strip()
        accounts = {a["id"]: a for a in load_kling_accounts()}
        account = accounts.get(account_id) or _pick_kling_account()
        if not account:
            continue

        _print(f"🧐 Poll Kling recovery — đơn {doc.id} ({account['nick']})...")
        try:
            lock = _submit_lock()
            with lock:
                profile = Path(account["profile_path"])
                sniffer = KlingNetworkSniffer()
                with sync_playwright() as p:
                    context = launch_kling_context(p, profile_path=profile)
                    page = context.pages[0] if context.pages else context.new_page()
                    sniffer.attach(page)
                    open_motion_control(page)
                    wait_for_login(page, timeout_sec=120)
                    timeout_sec = int(get_env("KLING_RECOVERY_POLL_SEC", "120"))
                    video_url = _poll_on_page(page, sniffer, timeout_sec)
                    context.close()
            if not video_url:
                _print(f"⏳ Chưa thấy video recovery cho {doc.id}")
                continue
            if skip_done and skip_done(doc.id, "đã completed"):
                continue
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            local = TMP_DIR / f"recovery_{doc.id}.mp4"
            _download_result(video_url, local)
            complete = _g.get("complete_order_with_video")
            if complete:
                complete(doc, str(local))
        except Exception as exc:
            _print(f"⚠️ Poll recovery {doc.id}: {exc}")


def processing_eligible(orders_cache: dict) -> list:
    """Đơn processing đủ thời gian để poll recovery."""
    eligible = []
    min_render = int(get_env("KLING_MIN_RENDER_SEC", get_env("BOT_MIN_RENDER_SEC", "180")))
    now = datetime.now(timezone.utc)
    for doc in orders_cache.values():
        data = doc.to_dict() or {}
        if data.get("status") != "processing":
            continue
        if data.get("renderProvider") != RENDER_PROVIDER_KLING:
            continue
        submitted = data.get("submittedAt")
        if submitted and (now - submitted).total_seconds() <= min_render:
            continue
        eligible.append(doc)
    return eligible
