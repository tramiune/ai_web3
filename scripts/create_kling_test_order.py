#!/usr/bin/env python3
"""Tạo đơn test Kling pending cho traderfinn0312@gmail.com (ảnh + video 3s)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import firebase_admin
import requests
from firebase_admin import credentials, firestore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kling_pricing import billable_seconds, cost_coins, cost_vnd
from tool98_api import trim_video_to_seconds

USER_EMAIL = "traderfinn0312@gmail.com"
WORKER = "https://motionai-upload-api.traderfinn0312.workers.dev"
DEMO_IMAGE = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&q=80&w=768"
DEMO_VIDEO = "https://pub-2b53cd37b4a44642afdbb8bb470bde66.r2.dev/banner.mp4"
VIDEO_SEC = 3.0
TMP = ROOT / "tmp_kling" / "test_order"
SA = ROOT / "serviceAccountKey.json"
if not SA.is_file():
    SA = ROOT.parent / "ai_web" / "serviceAccountKey.json"


def upload_bytes(data: bytes, folder: str, filename: str, content_type: str) -> str:
    file_name = f"{folder}/{int(time.time() * 1000)}_{filename}"
    url = f"{WORKER}/?file={requests.utils.quote(file_name, safe='')}"
    r = requests.post(url, data=data, headers={"Content-Type": content_type}, timeout=120)
    r.raise_for_status()
    body = r.json()
    if not body.get("url"):
        raise RuntimeError(f"Upload failed: {body}")
    return body["url"]


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)

    print("Download ảnh demo (model 1)...")
    img_bytes = requests.get(DEMO_IMAGE, timeout=60).content
    img_url = upload_bytes(img_bytes, "characters", "test_char_1.jpg", "image/jpeg")
    print("  ->", img_url)

    print("Download video + cắt 3s...")
    src_vid = TMP / "src.mp4"
    src_vid.write_bytes(requests.get(DEMO_VIDEO, timeout=120).content)
    trim_vid = TMP / "motion_3s.mp4"
    trim_video_to_seconds(src_vid, max_seconds=VIDEO_SEC, output=trim_vid)
    vid_url = upload_bytes(trim_vid.read_bytes(), "motions", "test_motion_3s.mp4", "video/mp4")
    print("  ->", vid_url)

    cred = credentials.Certificate(str(SA))
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    user_doc = None
    for doc in db.collection("users").where("email", "==", USER_EMAIL).limit(1).stream():
        user_doc = doc
        break
    if not user_doc:
        print(f"Không tìm thấy user {USER_EMAIL}")
        return 1

    uid = user_doc.id
    user = user_doc.to_dict() or {}
    coins = float(user.get("coins") or 0)
    bill_sec = billable_seconds(VIDEO_SEC)
    cost = cost_coins(VIDEO_SEC)
    vnd = cost_vnd(VIDEO_SEC)

    if coins < cost:
        print(f"⚠️ User chỉ còn {coins} coin, cần {cost}")

    order_ref = db.collection("orders").document()
    order = {
        "userId": uid,
        "userEmail": USER_EMAIL,
        "userName": user.get("displayName") or "Finn Trader",
        "packageName": "Nhanh",
        "modelId": "124",
        "serviceType": "motion-to-char",
        "serviceLabel": "Copy motion → ảnh",
        "costCoins": cost,
        "costVnd": vnd,
        "klingDurationSec": bill_sec,
        "promo1Coin": False,
        "characterImageLink": img_url,
        "referenceVideoLink": vid_url,
        "aspectRatio": "16:9",
        "vaeDurationSec": bill_sec,
        "vaeResolution": "720p",
        "renderProvider": "kling",
        "status": "pending",
        "resultLink": "",
        "adminNote": "test order bot local (script)",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }

    if coins < cost:
        raise RuntimeError(f"Khong du coin: {coins} < {cost}")
    user_doc.reference.update({
        "coins": coins - cost,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    order_ref.set(order)

    short = order_ref.id[-6:].upper()
    print(f"\n✅ Đã tạo đơn #{short}")
    print(f"   ID: {order_ref.id}")
    print(f"   Email: {USER_EMAIL}")
    print(f"   Video: {bill_sec}s | {cost} coin")
    print(f"   Status: pending → bot local sẽ nhận")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
