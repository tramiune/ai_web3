"""
RoboNeo team_studio — engine cho model Chất lượng (modelId 127) trên motionaistudio.cloud.
Dùng account pool + 115 credit/15s, xoay IP VNsProxy khi thiếu coin.
"""

from __future__ import annotations

import os
import re
import threading
import time

import requests

from project_env import get_env, load_project_env
from account_pool import (
    acquire_client_for_job,
    estimate_credits,
    list_accounts,
    list_eligible_accounts,
    max_accounts_per_ip,
    refresh_account_credits,
    update_account_after_job,
    video_duration_sec,
    _pool_path,
)
from roboneo_web import (
    RoboNeoAuthError,
    RoboNeoError,
    RoboNeoGatewayError,
    RoboNeoWebClient,
    resolve_motion_api,
    resolve_motion_mode,
    resolve_surface,
)
from videoaieasy_web import QUALITY_MODEL_IDS

load_project_env()

RENDER_PROVIDER_ROBONEO = "roboneo"
ROBONEO_MAX_CONCURRENT_PER_ACCOUNT = int(get_env("ROBONEO_MAX_CONCURRENT", "2"))

_g: dict = {}
_rb_clients: dict[str, RoboNeoWebClient] = {}
_rb_clients_lock = threading.Lock()
_rb_inflight: dict[str, int] = {}
_rb_inflight_lock = threading.Lock()


def wire(**kwargs):
    _g.update(kwargs)


def _roboneo_account_id(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def _pool_account(email: str) -> dict | None:
    email = (email or "").strip().lower()
    for row in list_accounts():
        if (row.get("email") or "").strip().lower() == email:
            return row
    return None


def _get_roboneo_client(account_id: str) -> RoboNeoWebClient:
    key = (account_id or "default").lower()
    with _rb_clients_lock:
        if key not in _rb_clients:
            _rb_clients[key] = RoboNeoWebClient(account_id=key)
        return _rb_clients[key]


def _reset_roboneo_client(account_id: str | None = None):
    with _rb_clients_lock:
        if account_id:
            _rb_clients.pop(account_id.lower(), None)
        else:
            _rb_clients.clear()


def _ensure_roboneo_session(client: RoboNeoWebClient, email: str, password: str):
    try:
        client.ensure_session()
        if (client._state.get("access_token") or "").strip():
            return
    except RoboNeoAuthError:
        pass
    from account_pool import _login_once

    client2, _ = _login_once(email, password, rotate=False)
    return client2


def _rb_inflight_inc(account_id: str):
    with _rb_inflight_lock:
        _rb_inflight[account_id] = _rb_inflight.get(account_id, 0) + 1


def _rb_inflight_dec(account_id: str):
    with _rb_inflight_lock:
        n = _rb_inflight.get(account_id, 0) - 1
        if n <= 0:
            _rb_inflight.pop(account_id, None)
        else:
            _rb_inflight[account_id] = n


def _count_rb_processing_for_email(email: str) -> int:
    db = _g["db"]
    cache = _g.get("processing_cache", {})
    cache_lock = _g.get("processing_cache_lock")
    email_l = email.strip().lower()
    cache_count = 0
    if cache_lock:
        with cache_lock:
            for doc in cache.values():
                d = doc.to_dict() or {}
                if d.get("status") == "processing" and (
                    (d.get("roboneoAccountEmail") or "").strip().lower() == email_l
                ):
                    cache_count += 1
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (
            db.collection("orders")
            .where(filter=FieldFilter("status", "==", "processing"))
            .where(filter=FieldFilter("roboneoAccountEmail", "==", email))
        )
        db_count = sum(1 for _ in q.stream())
        return max(cache_count, db_count)
    except Exception as e:
        print(f"⚠️ Đếm đơn RoboNeo nick {email}: {e}")
        return cache_count


def _rb_active_count(email: str) -> int:
    account_id = _roboneo_account_id(email)
    with _rb_inflight_lock:
        inflight = _rb_inflight.get(account_id, 0)
    return _count_rb_processing_for_email(email) + inflight


def quality_model_ids() -> frozenset[str]:
    return QUALITY_MODEL_IDS


def is_quality_order(order_data: dict | None) -> bool:
    model_id = str((order_data or {}).get("modelId") or "").strip()
    return model_id in QUALITY_MODEL_IDS


def _roboneo_surface() -> str:
    return resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))


def _roboneo_api_name() -> str:
    return resolve_motion_api(get_env("ROBONEO_QUALITY_MODEL", "v26"))


def _roboneo_mode() -> str:
    return get_env("ROBONEO_MOTION_MODE", "std") or "std"


def _task_status(data: dict) -> str:
    return str(
        data.get("state")
        or data.get("result_status")
        or (data.get("data") or {}).get("status")
        or data.get("status")
        or ""
    ).upper()


def _has_video_url(data: dict) -> bool:
    if data.get("last_image_url"):
        return True
    urls = data.get("initial_transferred_urls") or []
    if urls and urls[0]:
        return True
    for key in ("urls", "images"):
        vals = data.get(key) or (data.get("data") or {}).get(key) or []
        if vals and vals[0]:
            return True
    media_list = data.get("media_info_list") or (data.get("data") or {}).get("media_info_list") or []
    for item in media_list:
        if (item or {}).get("media_data"):
            return True
    return False


def _task_done(data: dict) -> bool:
    return _has_video_url(data)


def _task_success_empty(data: dict) -> bool:
    """RoboNeo báo SUCCESS nhưng không có URL video (render rỗng)."""
    if _has_video_url(data):
        return False
    return _task_status(data) in {"SUCCEED", "SUCCESS", "DONE", "10"}


def _task_failed(data: dict) -> bool:
    return _task_status(data) in {"FAILED", "FAIL", "ERROR"}


def _is_credit_error(err: object) -> bool:
    s = str(err or "").lower()
    return any(x in s for x in ("credit", "coin", "check_result", "không đủ", "insufficient"))


def submit_to_roboneo(order_id: str) -> bool:
    from xiaoyang_motion import (
        USER_NOTE_FILES_MISSING,
        USER_NOTE_SUBMIT_FAILED,
        _fail_order_processing,
        _mark_order_processing,
        _submit_engine_lock,
    )

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
    char_path = None
    vid_path = None
    data: dict = {}
    doc_ref = None
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

            from client_version import client_version_label, client_version_ok, min_client_version
            from user_order_notes import USER_NOTE_CLIENT_OUTDATED

            if not client_version_ok(data):
                print(
                    f"⛔ Đơn {order_id} — client cũ v{client_version_label(data)} "
                    f"(cần ≥ {min_client_version()})"
                )
                _fail_order_processing(
                    doc,
                    data,
                    f"clientVersion={client_version_label(data)}",
                    USER_NOTE_CLIENT_OUTDATED,
                    "client version",
                )
                return False

            img_url = (data.get("characterImageLink") or "").strip()
            vid_url = (data.get("referenceVideoLink") or "").strip()
            if not img_url or not vid_url:
                _fail_order_processing(
                    doc,
                    data,
                    "Thiếu characterImageLink hoặc referenceVideoLink",
                    USER_NOTE_FILES_MISSING,
                    "submit roboneo",
                )
                return False

            char_path = None
            vid_path = None
            download_file = _g["download_file"]
            session_error_backoff = _g.get("session_error_backoff", {})
            max_attempts = int(get_env("ROBONEO_SUBMIT_ATTEMPTS", "3"))
            excluded_nicks: set[str] = set()
            last_credit_err: str | None = None
            need = 0

            print(f"\n⚡ [NẠP ĐƠN / RoboNeo] {order_id} — model Chất lượng…")
            for dl in range(1, 3):
                if dl > 1:
                    print(f"🔄 Thử tải file lần {dl}...")
                char_path = download_file(img_url, f"char_{order_id}.png")
                vid_path = download_file(vid_url, f"vid_{order_id}.mp4")
                if char_path and vid_path:
                    break
                time.sleep(2)
            if not char_path or not vid_path:
                raise RoboNeoError("Không tải được ảnh/video từ link đơn hàng")

            duration = video_duration_sec(vid_path)
            need = estimate_credits(duration)
            print(f"→ Video ~{duration:.1f}s → cần ~{need} credit RoboNeo")

            for attempt in range(1, max_attempts + 1):
                account_email = ""
                account_id = ""
                try:
                    if attempt > 1:
                        print(
                            f"→ Retry RoboNeo {attempt}/{max_attempts} "
                            f"(đổi nick, đã loại {len(excluded_nicks)})…"
                        )

                    client, info = acquire_client_for_job(
                        need, exclude_emails=excluded_nicks
                    )
                    account_email = info.get("email") or ""
                    account_id = _roboneo_account_id(account_email)
                    _rb_inflight_inc(account_id)

                    active = _rb_active_count(account_email)
                    if active > ROBONEO_MAX_CONCURRENT_PER_ACCOUNT:
                        raise RoboNeoError("Nick RoboNeo đầy slot")

                    surface = _roboneo_surface()
                    api_name = _roboneo_api_name()
                    mode = _roboneo_mode()
                    pattern = resolve_motion_mode(mode)
                    prompt = (data.get("prompt") or get_env(
                        "ROBONEO_PROMPT", "Follow the reference motion naturally"
                    )).strip()

                    print(
                        f"🚀 [RoboNeo/{account_email}] {surface} | {api_name} | "
                        f"mode {mode} (pattern={pattern})"
                    )
                    client.init_config()
                    credit = client.meiye_query(surface=surface)
                    amount = int(credit.get("amount") or 0) if isinstance(credit, dict) else 0
                    if credit.get("check_result") is False or amount < need:
                        last_credit_err = f"Không đủ credit: cần ~{need}, có {amount} ({credit})"
                        print(f"⚠ {last_credit_err} — đổi nick…")
                        from account_pool import mark_account

                        mark_account(
                            account_email,
                            status="depleted",
                            note=last_credit_err,
                            credits=amount,
                        )
                        excluded_nicks.add(account_email.strip().lower())
                        _rb_inflight_dec(account_id)
                        account_id = ""
                        continue

                    room_id = client.create_room(surface=surface)
                    print("→ countcost …")
                    cost = client.count_cost(
                        api_name=api_name,
                        room_id=room_id,
                        model_pattern=pattern,
                        surface=surface,
                    )
                    cost_item = (cost.get("items") or [{}])[0] if isinstance(cost, dict) else {}
                    fallback = cost_item.get("fallback_cost")
                    print(
                        f"  cost={cost_item.get('cost')} real_cost={cost_item.get('real_cost')} "
                        f"fallback={fallback}"
                    )
                    required = need
                    for val in (fallback, cost_item.get("real_cost"), cost_item.get("cost")):
                        if val is not None:
                            try:
                                required = max(required, int(val))
                            except (TypeError, ValueError):
                                pass
                    if amount < required:
                        last_credit_err = (
                            f"Credit {amount} < cost thực {required} "
                            f"(ước tính ~{need}, fallback={fallback})"
                        )
                        print(f"⚠ {last_credit_err} — đổi nick…")
                        from account_pool import mark_account

                        mark_account(
                            account_email,
                            status="depleted",
                            note=last_credit_err,
                            credits=amount,
                        )
                        excluded_nicks.add(account_email.strip().lower())
                        _rb_inflight_dec(account_id)
                        account_id = ""
                        continue

                    image_up = client.upload_file(char_path, surface=surface)
                    video_up = client.upload_file(vid_path, surface=surface)
                    workflow = client.build_motion_workflow(
                        char_path,
                        image_up["url"],
                        image_up["asset_id"],
                        vid_path,
                        video_up["url"],
                        video_up["asset_id"],
                        prompt=prompt,
                        api_name=api_name,
                    )
                    task_id = client.node_execute(
                        room_id,
                        workflow,
                        api_name=api_name,
                        prompt=prompt,
                        model_pattern=pattern,
                        surface=surface,
                    )
                    print(f"🆔 [RoboNeo/{account_email}] room={room_id} task={task_id}")
                    _mark_order_processing(
                        doc_ref,
                        task_id,
                        provider=RENDER_PROVIDER_ROBONEO,
                        roboneo_room_id=room_id,
                        roboneo_account_email=account_email,
                    )
                    remaining = refresh_account_credits(client, account_email)
                    update_account_after_job(account_email, remaining)
                    print(f"→ Nick {account_email} còn {remaining} credit sau nạp đơn")
                    session_error_backoff.pop(order_id, None)
                    print(f"✅ Đơn {order_id} → processing (RoboNeo, {account_email})")
                    try:
                        short_id = order_id[-6:].upper()
                        min_sec = int(get_env("ROBONEO_MIN_RENDER_SEC", "300"))
                        _g["send_telegram_message"](
                            f"⚙️ <b>ĐƠN HÀNG ĐANG XỬ LÝ</b> (RoboNeo Chất lượng)\n\n"
                            f"🆔 Mã đơn: #{short_id}\n"
                            f"📧 Nick: {account_email}\n"
                            f"🤖 Task: <code>{task_id}</code>\n"
                            f"⏳ Poll sau {min_sec // 60} phút..."
                        )
                    except Exception:
                        pass
                    success = True
                    break
                except (
                    requests.RequestException,
                    RoboNeoAuthError,
                    RoboNeoGatewayError,
                    RoboNeoError,
                ) as e:
                    if account_email:
                        from account_pool import mark_account

                        mark_account(account_email, status="depleted", note=str(e))
                        excluded_nicks.add(account_email.strip().lower())
                    if _is_credit_error(e) and attempt < max_attempts:
                        last_credit_err = str(e)
                        print(f"⚠ {e} — thử nick khác…")
                        continue
                    raise
                finally:
                    if account_id:
                        _rb_inflight_dec(account_id)

            if success:
                return True

            # Hết nick — giữ pending, retry sau (không hoàn coin khách)
            backoff_sec = int(get_env("ROBONEO_CREDIT_BACKOFF_SEC", "120"))
            session_error_backoff[order_id] = time.time() + backoff_sec
            err_msg = last_credit_err or f"Không có nick đủ credit sau {max_attempts} lần"
            print(f"⏸ Đơn {order_id} chờ retry sau {backoff_sec}s — {err_msg}")
            _g["notify_internal_error_telegram"](
                order_id, data, err_msg, "submit roboneo (thiếu credit, sẽ retry)"
            )
            return False
    except (
        requests.RequestException,
        RoboNeoAuthError,
        RoboNeoGatewayError,
        RoboNeoError,
    ) as e:
        if _is_credit_error(e):
            backoff_sec = int(get_env("ROBONEO_CREDIT_BACKOFF_SEC", "120"))
            _g.get("session_error_backoff", {})[order_id] = time.time() + backoff_sec
            print(f"⏸ Đơn {order_id} chờ retry sau {backoff_sec}s — {e}")
            _g["notify_internal_error_telegram"](
                order_id, data, str(e), "submit roboneo (thiếu credit, sẽ retry)"
            )
            return False
        print(f"❌ Nạp RoboNeo thất bại {order_id}: {e}")
        _g["notify_internal_error_telegram"](order_id, data, str(e), "submit roboneo")
        if doc_ref is not None:
            doc = doc_ref.get()
            data = doc.to_dict() or {}
            if data.get("status") == "pending":
                _fail_order_processing(
                    doc,
                    data,
                    str(e),
                    USER_NOTE_SUBMIT_FAILED,
                    "submit roboneo",
                )
        return False
    finally:
        if char_path and os.path.exists(char_path):
            os.remove(char_path)
        if vid_path and os.path.exists(vid_path):
            os.remove(vid_path)
        with submitting_lock:
            submitting.discard(order_id)
    return success


def poll_roboneo_orders(orders_to_check):
    from xiaoyang_motion import USER_NOTE_ORDER_FAILED, _fail_order_processing

    skip_done = _g.get("skip_if_order_done")
    complete = _g["complete_order_with_video"]
    surface = _roboneo_surface()

    for doc in orders_to_check:
        order_data = doc.to_dict() or {}
        task_id = str(order_data.get("roboneoTaskId") or "").strip()
        room_id = str(order_data.get("roboneoRoomId") or "").strip()
        email = (order_data.get("roboneoAccountEmail") or "").strip()
        if not task_id or not room_id:
            continue
        nick = email or "?"
        print(f"🧐 RoboNeo — task {task_id} (đơn {doc.id}, {nick})...")
        acc = _pool_account(email)
        if not acc:
            print(f"⚠️ Không tìm thấy nick {email} trong pool")
            continue
        account_id = _roboneo_account_id(email)
        local_path = f"res_{doc.id}.mp4"
        try:
            client = _get_roboneo_client(account_id)
            client = _ensure_roboneo_session(client, email, acc["password"]) or client
            data = client.node_execute_query(room_id, task_id, surface=surface)
        except (RoboNeoAuthError, RoboNeoGatewayError, RoboNeoError) as e:
            print(f"❌ Poll RoboNeo {task_id}: {e}")
            if isinstance(e, RoboNeoAuthError):
                _reset_roboneo_client(account_id)
            continue
        except Exception as e:
            print(f"❌ Poll RoboNeo {task_id}: {e}")
            continue

        status = _task_status(data)
        print(f"   status={status}")
        if _task_failed(data):
            _fail_order_processing(
                doc,
                order_data,
                f"RoboNeo task {task_id} FAIL: {data}",
                USER_NOTE_ORDER_FAILED,
                "render roboneo",
            )
        elif _task_success_empty(data):
            _fail_order_processing(
                doc,
                order_data,
                f"RoboNeo task {task_id} SUCCESS nhưng không có video (render rỗng): {data}",
                USER_NOTE_ORDER_FAILED,
                "render roboneo",
            )
        elif _task_done(data):
            if skip_done and skip_done(doc.id, "đã completed"):
                continue
            try:
                video_url = client.extract_video_url(data)
                print(f"🎉 RoboNeo task {task_id} HOÀN TẤT — tải {video_url[:80]}…")
                r = client.session.get(video_url, timeout=300)
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    f.write(r.content)
                refresh_account_credits(client, email)
                complete(doc, local_path)
            except Exception as e:
                print(f"⚠️ Lỗi tải/hoàn đơn {doc.id}: {e}")
                _fail_order_processing(
                    doc,
                    order_data,
                    str(e),
                    USER_NOTE_ORDER_FAILED,
                    "render roboneo download",
                )
        else:
            print(f"⏳ Task {task_id} vẫn {status or 'RUNNING'}")


def log_pool_on_startup():
    rows = list_eligible_accounts(1)
    all_rows = [a for a in list_accounts() if a.get("status") in ("active", "depleted")]
    known = sum(1 for a in all_rows if a.get("credits") is not None)
    path = _pool_path()
    print(
        f"👥 RoboNeo pool: {len(all_rows)} nick (active+depleted) | "
        f"{len(rows)} sẵn sàng thử | {known} đã biết credit | "
        f"file {path} | "
        f"max {ROBONEO_MAX_CONCURRENT_PER_ACCOUNT} đơn/nick | "
        f"{max_accounts_per_ip()} nick/IP VNsProxy | "
        f"surface {_roboneo_surface()} | model {_roboneo_api_name()}"
    )
    for row in sorted(all_rows, key=lambda a: -(int(a.get("credits") or 0)))[:10]:
        print(f"  • {row.get('email')} — {row.get('credits', '?')} credit ({row.get('status')})")
