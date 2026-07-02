"""RoboNeo relay — xử lý job từ site khác (Motion) qua HTTP, dùng pool Kaling."""

from __future__ import annotations

import os
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from project_env import get_env, load_project_env
from account_pool import (
    acquire_client_for_job,
    mark_account,
    pick_credits_for_job,
    refresh_account_credits,
    release_reserved,
    required_credits_from_cost,
    update_account_after_job,
    video_duration_sec,
)
from roboneo_web import (
    RoboNeoAuthError,
    RoboNeoError,
    RoboNeoGatewayError,
    RoboNeoWebClient,
    resolve_motion_mode,
    resolve_surface,
)

load_project_env()

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_download_fn: Callable[..., str | None] | None = None


def wire(*, download_file: Callable[..., str | None]) -> None:
    global _download_fn
    _download_fn = download_file


def relay_enabled() -> bool:
    raw = (get_env("ROBONEO_RELAY_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def relay_secret() -> str:
    return (get_env("ROBONEO_RELAY_SECRET") or "").strip()


def _check_secret(got: str) -> None:
    want = relay_secret()
    if not want:
        raise PermissionError("ROBONEO_RELAY_SECRET chưa cấu hình")
    if not secrets.compare_digest((got or "").strip(), want):
        raise PermissionError("Relay secret sai")


def _roboneo_account_id(email: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", (email or "").strip().lower()).strip("_") or "default"


def _task_status(data: dict) -> str:
    return str(data.get("state") or data.get("status") or "").upper()


def _task_done(data: dict) -> bool:
    return _task_status(data) in {"SUCCEED", "SUCCESS", "DONE", "10"}


def _task_failed(data: dict) -> bool:
    return _task_status(data) in {"FAILED", "FAIL", "ERROR"}


def _has_video_url(data: dict) -> bool:
    from roboneo_motion import _has_video_url

    return _has_video_url(data)


def _is_credit_error(err: object) -> bool:
    s = str(err or "").lower()
    return any(x in s for x in ("credit", "coin", "check_result", "không đủ", "insufficient"))


def _normalize_order_data(payload: dict[str, Any]) -> dict[str, Any]:
    max_sec = float(payload.get("maxVideoSec") or payload.get("vaeDurationSec") or 10)
    return {
        "maxVideoSec": max_sec,
        "vaeDurationSec": int(payload.get("vaeDurationSec") or max_sec),
        "vaeResolution": (payload.get("vaeResolution") or "720p").strip() or "720p",
        "prompt": (payload.get("prompt") or "").strip(),
        "modelId": str(payload.get("modelId") or "").strip(),
    }


def submit_relay_job(payload: dict[str, Any]) -> dict[str, Any]:
    _check_secret(str(payload.get("secret") or ""))
    if not _download_fn:
        raise RuntimeError("Relay chưa wire download_file")

    site = (payload.get("site") or "motion").strip().lower()
    external_id = (payload.get("externalOrderId") or "").strip()
    img_url = (payload.get("characterImageLink") or "").strip()
    vid_url = (payload.get("referenceVideoLink") or "").strip()
    if not external_id or not img_url or not vid_url:
        raise ValueError("Thiếu externalOrderId / characterImageLink / referenceVideoLink")

    relay_id = uuid.uuid4().hex
    label = f"{site}_{external_id}"
    order_data = _normalize_order_data(payload)
    work_dir = Path(tempfile.mkdtemp(prefix=f"relay_{relay_id}_"))
    char_path = vid_path = None

    print(f"\n⚡ [RoboNeo relay] {label} từ {site}")
    try:
        for dl in range(1, 3):
            if dl > 1:
                print("🔄 Thử tải file relay lần 2…")
            char_path = _download_fn(img_url, f"relay_char_{relay_id}.png")
            vid_path = _download_fn(vid_url, f"relay_vid_{relay_id}.mp4")
            if char_path and vid_path:
                break
            time.sleep(2)
        if not char_path or not vid_path:
            raise RoboNeoError("Không tải được ảnh/video relay")

        from order_media import trim_reference_video_for_order

        vid_path = trim_reference_video_for_order(vid_path, order_data)

        ref_plan = None
        try:
            from roboneo_reference import prepare_roboneo_reference

            vid_path, ref_plan = prepare_roboneo_reference(
                Path(vid_path), work_dir
            )
            vid_path = str(vid_path)
        except Exception as prep_err:
            print(f"⚠️ Relay speed/trim: {prep_err}")

        duration = video_duration_sec(vid_path)
        need, pick_need = pick_credits_for_job(duration)
        max_attempts = int(get_env("ROBONEO_SUBMIT_ATTEMPTS", "3"))
        excluded: set[str] = set()
        surface = resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))
        from roboneo_motion import _roboneo_api_name, _roboneo_mode

        api_name = _roboneo_api_name()
        mode = _roboneo_mode()
        pattern = resolve_motion_mode(mode)
        prompt = (order_data.get("prompt") or get_env(
            "ROBONEO_PROMPT", "Follow the reference motion naturally"
        )).strip()

        task_id = room_id = account_email = ""
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            reserved_amt = 0
            client = None
            account_id = ""
            try:
                if attempt > 1:
                    from account_pool import rotate_proxy_for_retry

                    rotate_proxy_for_retry()
                client, info = acquire_client_for_job(
                    pick_need, exclude_emails=excluded
                )
                account_email = info.get("email") or ""
                account_id = _roboneo_account_id(account_email)
                reserved_amt = int(info.get("reserved") or pick_need)

                client.init_config()
                credit = client.meiye_query(surface=surface)
                amount = int(credit.get("amount") or 0) if isinstance(credit, dict) else 0
                if credit.get("check_result") is False or amount < pick_need:
                    mark_account(
                        account_email,
                        status="depleted",
                        note=f"relay: credit {amount} < {pick_need}",
                        credits=amount,
                    )
                    excluded.add(account_email.strip().lower())
                    release_reserved(account_email, reserved_amt)
                    reserved_amt = 0
                    continue

                room_id = client.create_room(surface=surface)
                cost = client.count_cost(
                    api_name=api_name,
                    room_id=room_id,
                    model_pattern=pattern,
                    surface=surface,
                )
                cost_item = (cost.get("items") or [{}])[0] if isinstance(cost, dict) else {}
                required = required_credits_from_cost(
                    estimate=need, cost_item=cost_item
                )
                if amount < required:
                    mark_account(
                        account_email,
                        status="depleted",
                        note=f"relay: {amount} < {required}",
                        credits=amount,
                    )
                    excluded.add(account_email.strip().lower())
                    release_reserved(account_email, reserved_amt)
                    reserved_amt = 0
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
                remaining = refresh_account_credits(
                    client, account_email, surface=surface, release_reserved_amount=reserved_amt
                )
                reserved_amt = 0
                update_account_after_job(account_email, remaining)
                print(
                    f"✅ Relay {label} → task {task_id} nick {account_email} "
                    f"(còn {remaining} cr)"
                )
                last_err = None
                break
            except Exception as e:
                last_err = e
                if account_email:
                    if reserved_amt > 0:
                        release_reserved(account_email, reserved_amt)
                    if not _is_credit_error(e):
                        try:
                            refresh_account_credits(
                                client, account_email, surface=surface
                            )
                        except Exception:
                            pass
                    mark_account(account_email, status="depleted", note=str(e))
                    excluded.add(account_email.strip().lower())
                if attempt >= max_attempts:
                    raise
                print(f"⚠ Relay submit retry {attempt}: {e}")
        if not task_id:
            raise RoboNeoError(str(last_err or "Không nạp được relay"))

        job = {
            "relayId": relay_id,
            "site": site,
            "externalOrderId": external_id,
            "taskId": task_id,
            "roomId": room_id,
            "accountEmail": account_email,
            "refPlan": ref_plan.to_dict() if ref_plan else None,
            "status": "processing",
            "videoPath": None,
            "error": None,
            "workDir": str(work_dir),
            "createdAt": time.time(),
        }
        with _jobs_lock:
            _jobs[relay_id] = job
        return {
            "ok": True,
            "relayId": relay_id,
            "taskId": task_id,
            "roomId": room_id,
            "accountEmail": account_email,
            "refPlan": job["refPlan"],
        }
    finally:
        if char_path and os.path.exists(char_path):
            os.remove(char_path)
        if vid_path and os.path.exists(vid_path):
            try:
                os.remove(vid_path)
            except OSError:
                pass


def get_relay_job(relay_id: str, *, secret: str = "") -> dict[str, Any]:
    _check_secret(secret)
    with _jobs_lock:
        job = _jobs.get(relay_id)
    if not job:
        raise KeyError("relay job không tồn tại")
    return dict(job)


def poll_relay_job(relay_id: str, *, secret: str = "") -> dict[str, Any]:
    job = get_relay_job(relay_id, secret=secret)
    if job.get("status") == "done":
        return {"status": "done", "relayId": relay_id, "hasVideo": bool(job.get("videoPath"))}
    if job.get("status") == "failed":
        return {"status": "failed", "relayId": relay_id, "error": job.get("error")}

    from account_pool import list_accounts

    email = job.get("accountEmail") or ""
    acc = next(
        (a for a in list_accounts() if (a.get("email") or "").lower() == email.lower()),
        None,
    )
    if not acc:
        raise RoboNeoError(f"Nick relay {email} không có trong pool")

    from roboneo_motion import _ensure_roboneo_session, _get_roboneo_client

    surface = resolve_surface(get_env("ROBONEO_SURFACE", "team_studio"))
    account_id = _roboneo_account_id(email)
    client = _get_roboneo_client(account_id)
    client = _ensure_roboneo_session(client, email, acc["password"]) or client
    data = client.node_execute_query(job["roomId"], job["taskId"], surface=surface)
    st = _task_status(data)
    print(f"🧐 Relay poll {relay_id[:8]}… status={st}")

    if _task_failed(data) or (_task_done(data) and not _has_video_url(data)):
        err = f"RoboNeo relay FAIL: {data}"
        with _jobs_lock:
            job = _jobs.get(relay_id) or job
            job["status"] = "failed"
            job["error"] = err
            _jobs[relay_id] = job
        return {"status": "failed", "relayId": relay_id, "error": err}

    if not _task_done(data):
        return {"status": "processing", "relayId": relay_id, "taskStatus": st}

    video_url = client.extract_video_url(data)
    raw_path = Path(job["workDir"]) / "raw.mp4"
    r = client.session.get(video_url, timeout=300)
    r.raise_for_status()
    raw_path.write_bytes(r.content)

    final_path = raw_path
    ref_plan_raw = job.get("refPlan")
    if ref_plan_raw:
        try:
            from roboneo_reference import plan_from_dict, restore_roboneo_output

            plan = plan_from_dict(ref_plan_raw)
            if plan and plan.branch == "speed_up":
                final_path = Path(job["workDir"]) / "final.mp4"
                final_path = restore_roboneo_output(
                    raw_path, plan, Path(job["workDir"])
                )
        except Exception as restore_err:
            print(f"⚠ Relay restore speed: {restore_err}")

    with _jobs_lock:
        job = _jobs.get(relay_id) or job
        job["status"] = "done"
        job["videoPath"] = str(final_path)
        _jobs[relay_id] = job
    refresh_account_credits(client, email, surface=surface)
    return {"status": "done", "relayId": relay_id, "hasVideo": True}


def read_relay_video(relay_id: str, *, secret: str = "") -> tuple[bytes, str]:
    job = get_relay_job(relay_id, secret=secret)
    if job.get("status") != "done":
        raise FileNotFoundError("Video chưa sẵn sàng")
    path = Path(job.get("videoPath") or "")
    if not path.is_file():
        raise FileNotFoundError("Video relay mất")
    return path.read_bytes(), path.name
