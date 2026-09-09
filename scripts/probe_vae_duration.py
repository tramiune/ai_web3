#!/usr/bin/env python3
"""Probe VAE API — test create job 10s / 20s / 30s (không đụng bot)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from project_env import load_project_env  # noqa: E402
from videoaieasy_web import (  # noqa: E402
    VAE_API_MODEL_WEAVY,
    MODEL_KLING_26,
    VideoAiEasyClient,
    VideoAiEasyError,
    normalize_vae_resolution,
)

# Asset nhỏ public (demo) — chỉ dùng để test POST /api/jobs
TEST_IMAGE = (
    "https://images.unsplash.com/photo-1534528741775-53994a69daeb"
    "?auto=format&fit=crop&w=512&h=912&q=80"
)
TEST_VIDEO = (
    "https://pub-4496e76c4ba34c28980998855e485fbd.r2.dev/demo/motion_ref.mp4"
)


def probe_case(
    client: VideoAiEasyClient,
    *,
    label: str,
    duration_sec: int,
    api_model: str,
    resolution: str | None,
) -> str:
    res = normalize_vae_resolution(resolution)
    print(f"\n--- {label} | model={api_model} dur={duration_sec}s res={res} ---")
    try:
        job_id = client.create_motion_job(
            input_image_url=TEST_IMAGE,
            driving_video_url=TEST_VIDEO,
            duration_sec=duration_sec,
            api_model=api_model,
            resolution=res,
        )
        print(f"✅ OK — jobId={job_id}")
        return "ok"
    except VideoAiEasyError as e:
        msg = str(e)
        print(f"❌ FAIL — {msg}")
        if "503" in msg or "bảo trì" in msg.lower():
            return "maintenance"
        return "error"
    except Exception as e:
        print(f"❌ FAIL — {e}")
        return "error"


def main() -> int:
    load_project_env()
    accounts_raw = (__import__("os").environ.get("VIDEOAIEASY_ACCOUNTS") or "").strip()
    if not accounts_raw:
        print("❌ Thiếu VIDEOAIEASY_ACCOUNTS")
        return 1
    email, _, password = accounts_raw.partition(":")
    password = password.strip()
    email = email.strip()
    if not email or not password:
        print("❌ VIDEOAIEASY_ACCOUNTS sai format email:pass")
        return 1

    client = VideoAiEasyClient(account_id=email.split("@")[0])
    prof = client.ensure_session(email, password)
    credits = prof.get("credits") if isinstance(prof, dict) else "?"
    print(f"🔐 VAE login OK — {email} | credits={credits}")

    cases = [
        ("weavy 10s 720p", 10, VAE_API_MODEL_WEAVY, "720p"),
        ("weavy 20s 720p", 20, VAE_API_MODEL_WEAVY, "720p"),
        ("weavy 30s 720p", 30, VAE_API_MODEL_WEAVY, "720p"),
        ("kling-2.6 20s 1080p", 20, MODEL_KLING_26, "1080p"),
        ("kling-2.6 10s 1080p", 10, MODEL_KLING_26, "1080p"),
    ]
    results: dict[str, str] = {}
    for label, dur, model, res in cases:
        results[label] = probe_case(
            client, label=label, duration_sec=dur, api_model=model, resolution=res
        )

    print("\n=== TÓM TẮT ===")
    for k, v in results.items():
        icon = "✅" if v == "ok" else ("🚧" if v == "maintenance" else "❌")
        print(f"  {icon} {k}: {v}")

    twenty = results.get("weavy 20s 720p", "error")
    if twenty == "ok":
        print("\n→ VAE 20s (weavy-kling-26) ĐANG MỞ — có thể nạp bot.")
    elif twenty == "maintenance":
        print("\n→ VAE 20s vẫn BẢO TRÌ (503) — chưa nên bật bot.")
    else:
        print("\n→ VAE 20s lỗi khác — cần xem chi tiết trên.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
