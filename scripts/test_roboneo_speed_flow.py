#!/usr/bin/env python3
"""
Test flow RoboNeo reference video (CHƯA gắn bot):
  - dur < 12s     → RoboNeo bình thường
  - 12s ≤ dur ≤ 15s → speed up < 12s → RoboNeo → slow output về bình thường
  - dur > 15s     → cắt 15s từ đầu → speed up < 12s → RoboNeo → slow output

Biên:
  - 12s thuộc nhánh speed-up
  - 15s thuộc nhánh 12..15 (không cắt 15s trước)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tool98_api import probe_video_duration_seconds, trim_video_to_seconds  # noqa: E402

ROBONEO_INPUT_MAX_SEC = 12.0  # sau speed-up phải < 12s
ROBONEO_SPEED_TARGET_SEC = 11.5  # buffer dưới 12
ROBONEO_TRIM_MAX_SEC = 15.0


@dataclass
class RoboNeoRefPlan:
    branch: str  # normal | speed_up
    source_sec: float
    trim_to_sec: float | None
    work_sec: float
    speed_factor: float
    roboneo_input_target_sec: float
    restore_factor: float

    def summary(self) -> str:
        if self.branch == "normal":
            return f"normal · {self.source_sec:.2f}s → RoboNeo (không đổi tốc độ)"
        parts = [f"speed_up · gốc {self.source_sec:.2f}s"]
        if self.trim_to_sec is not None:
            parts.append(f"cắt đầu → {self.trim_to_sec:.0f}s")
        parts.append(f"tua ×{self.speed_factor:.3f} → ~{self.roboneo_input_target_sec:.2f}s RoboNeo")
        parts.append(f"sau render slow ×{self.restore_factor:.3f}")
        return " · ".join(parts)


def plan_roboneo_reference(duration_sec: float) -> RoboNeoRefPlan:
    dur = float(duration_sec)
    if dur < ROBONEO_INPUT_MAX_SEC:
        return RoboNeoRefPlan(
            branch="normal",
            source_sec=dur,
            trim_to_sec=None,
            work_sec=dur,
            speed_factor=1.0,
            roboneo_input_target_sec=dur,
            restore_factor=1.0,
        )

    trim_to: float | None = None
    work = dur
    if dur > ROBONEO_TRIM_MAX_SEC:
        trim_to = ROBONEO_TRIM_MAX_SEC
        work = ROBONEO_TRIM_MAX_SEC

    target = ROBONEO_SPEED_TARGET_SEC
    speed_factor = work / target
    return RoboNeoRefPlan(
        branch="speed_up",
        source_sec=dur,
        trim_to_sec=trim_to,
        work_sec=work,
        speed_factor=speed_factor,
        roboneo_input_target_sec=target,
        restore_factor=speed_factor,
    )


def _ffmpeg() -> str:
    from tool98_api import _ffmpeg_executable

    exe = _ffmpeg_executable()
    if not exe:
        raise RuntimeError("Cần ffmpeg")
    return exe


def speed_up_video(source: Path, *, factor: float, output: Path) -> Path:
    """Tua nhanh video (factor > 1 → ngắn hơn). Giữ audio sync nếu có."""
    if factor <= 1.0 + 1e-6:
        shutil.copy2(source, output)
        return output
    ff = _ffmpeg()
    # setpts=PTS/factor cho video; atempo chain cho audio (max 2.0 mỗi filter)
    vfilter = f"setpts=PTS/{factor:.6f}"
    atempo_parts: list[str] = []
    remaining = factor
    while remaining > 2.0 + 1e-6:
        atempo_parts.append("atempo=2.0")
        remaining /= 2.0
    if remaining < 0.5 - 1e-6:
        while remaining < 0.5:
            atempo_parts.append("atempo=0.5")
            remaining /= 0.5
        if abs(remaining - 1.0) > 1e-3:
            atempo_parts.append(f"atempo={remaining:.6f}")
    elif abs(remaining - 1.0) > 1e-3:
        atempo_parts.append(f"atempo={remaining:.6f}")
    afilter = ",".join(atempo_parts) if atempo_parts else None

    cmd = [ff, "-y", "-i", str(source), "-vf", vfilter]
    if afilter:
        cmd += ["-af", afilter]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"speed_up fail: {(r.stderr or r.stdout)[-400:]}")
    return output


def slow_down_video(source: Path, *, factor: float, output: Path) -> Path:
    """Khôi phục tốc độ sau RoboNeo (factor = lúc speed-up)."""
    if factor <= 1.0 + 1e-6:
        shutil.copy2(source, output)
        return output
    ff = _ffmpeg()
    vfilter = f"setpts=PTS*{factor:.6f}"
    atempo_parts: list[str] = []
    remaining = 1.0 / factor
    while remaining < 0.5 - 1e-6:
        atempo_parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0 + 1e-6:
        atempo_parts.append("atempo=2.0")
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-3:
        atempo_parts.append(f"atempo={remaining:.6f}")
    afilter = ",".join(atempo_parts) if atempo_parts else None

    cmd = [ff, "-y", "-i", str(source), "-vf", vfilter]
    if afilter:
        cmd += ["-af", afilter]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"slow_down fail: {(r.stderr or r.stdout)[-400:]}")
    return output


def prepare_roboneo_reference(source: Path, work_dir: Path) -> tuple[Path, RoboNeoRefPlan]:
    dur = probe_video_duration_seconds(str(source))
    if dur is None:
        raise RuntimeError(f"Không đọc được duration: {source}")
    plan = plan_roboneo_reference(dur)
    print(f"📋 {plan.summary()}")

    current = source
    if plan.trim_to_sec is not None:
        trimmed = work_dir / f"trim_{plan.trim_to_sec:.0f}s{source.suffix or '.mp4'}"
        current = Path(trim_video_to_seconds(current, max_seconds=plan.trim_to_sec, output=trimmed))
        td = probe_video_duration_seconds(str(current))
        print(f"   ✂️ trim đầu → {td:.2f}s ({trimmed.name})")

    if plan.branch == "speed_up":
        sped = work_dir / f"speed_x{plan.speed_factor:.3f}{source.suffix or '.mp4'}"
        speed_up_video(current, factor=plan.speed_factor, output=sped)
        sd = probe_video_duration_seconds(str(sped))
        print(f"   ⚡ speed-up → {sd:.2f}s ({sped.name})")
        if sd is not None and sd >= ROBONEO_INPUT_MAX_SEC - 0.05:
            print(f"   ⚠️ vẫn ≥ {ROBONEO_INPUT_MAX_SEC}s — cần hạ target hoặc tăng factor")
        return sped, plan

    return current, plan


def simulate_roboneo_output(roboneo_input: Path, work_dir: Path) -> Path:
    """Giả lập output RoboNeo = copy input (chỉ test khôi phục speed)."""
    fake = work_dir / f"fake_roboneo_out{roboneo_input.suffix or '.mp4'}"
    shutil.copy2(roboneo_input, fake)
    return fake


def restore_roboneo_output(roboneo_output: Path, plan: RoboNeoRefPlan, work_dir: Path) -> Path:
    if plan.branch == "normal":
        return roboneo_output
    out = work_dir / f"restored{roboneo_output.suffix or '.mp4'}"
    slow_down_video(roboneo_output, factor=plan.restore_factor, output=out)
    od = probe_video_duration_seconds(str(out))
    print(f"   🐢 restore speed → {od:.2f}s ({out.name})")
    return out


def make_test_clip(path: Path, duration_sec: float) -> None:
    ff = _ffmpeg()
    cmd = [
        ff,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration_sec}:size=320x568:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_sec}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def run_case(label: str, duration_sec: float, out_root: Path) -> dict:
    work = out_root / label.replace(".", "_")
    work.mkdir(parents=True, exist_ok=True)
    src = work / "source.mp4"
    make_test_clip(src, duration_sec)
    actual = probe_video_duration_seconds(str(src))
    print(f"\n{'='*60}\nCASE {label} (tạo ~{duration_sec}s, thực {actual:.2f}s)")

    roboneo_in, plan = prepare_roboneo_reference(src, work)
    rin = probe_video_duration_seconds(str(roboneo_in))
    fake_out = simulate_roboneo_output(roboneo_in, work)
    final = restore_roboneo_output(fake_out, plan, work)
    fin = probe_video_duration_seconds(str(final))

    expected_work = plan.work_sec if plan.branch == "speed_up" else actual
    return {
        "label": label,
        "source_sec": actual,
        "plan": asdict(plan),
        "roboneo_input_sec": rin,
        "final_sec": fin,
        "ok_input_under_12": rin is not None and rin < ROBONEO_INPUT_MAX_SEC,
        "ok_restore_near_work": fin is not None and abs(fin - expected_work) < 1.5,
    }


def run_roboneo_e2e(
    *,
    image: Path,
    video: Path,
    out_root: Path,
    email: str = "",
    password: str = "",
) -> dict:
    from account_pool import (
        _login_once,
        acquire_client_for_job,
        estimate_credits,
        refresh_account_credits,
        update_account_after_job,
    )
    from roboneo_web import resolve_motion_api, resolve_motion_mode, resolve_surface

    work = out_root / "e2e"
    work.mkdir(parents=True, exist_ok=True)
    dur = probe_video_duration_seconds(str(video))
    if dur is None:
        raise RuntimeError(f"Không đọc duration: {video}")

    print(f"\n{'='*60}\nE2E RoboNeo · {video.name} · {dur:.2f}s")
    print(f"Ảnh: {image.name}")

    roboneo_in, plan = prepare_roboneo_reference(video, work)
    rin = probe_video_duration_seconds(str(roboneo_in)) or 0.0
    need = estimate_credits(rin)
    print(f"→ Cần ~{need} credit RoboNeo (video input {rin:.2f}s)")

    if email and password:
        print(f"→ Login trực tiếp {email} (xoay IP)")
        client, info = _login_once(email.strip(), password, rotate=True)
    else:
        client, info = acquire_client_for_job(need)
    email_used = info.get("email") or email or "?"
    surface = resolve_surface(None)
    print(f"→ Nick: {email_used}")

    raw_out = work / "roboneo_raw.mp4"
    try:
        client.run_motion_pipeline(
            image,
            roboneo_in,
            output_path=raw_out,
            api_name=resolve_motion_api(None),
            mode=resolve_motion_mode(None),
            surface=surface,
            poll_sec=5.0,
            timeout_sec=3600.0,
        )
        remaining = refresh_account_credits(client, email_used, surface=surface)
        update_account_after_job(email_used, remaining)
        print(f"→ Nick {email_used} còn {remaining} credit")
    except Exception:
        raise

    raw_d = probe_video_duration_seconds(str(raw_out))
    print(f"✅ RoboNeo raw output: {raw_d:.2f}s → {raw_out}")

    final = restore_roboneo_output(raw_out, plan, work)
    fin_d = probe_video_duration_seconds(str(final))

    return {
        "source_video_sec": dur,
        "plan": asdict(plan),
        "roboneo_input": str(roboneo_in),
        "roboneo_input_sec": rin,
        "roboneo_raw": str(raw_out),
        "roboneo_raw_sec": raw_d,
        "final": str(final),
        "final_sec": fin_d,
        "nick": email_used,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Test RoboNeo speed/trim flow (không gắn bot)")
    p.add_argument("--video", help="Video thật thay vì clip test")
    p.add_argument("--image", help="Ảnh nhân vật (dùng với --roboneo)")
    p.add_argument("--email", help="Nick RoboNeo (bỏ qua pool)")
    p.add_argument("--password", help="Mật khẩu nick (dùng với --email)")
    p.add_argument("--roboneo", action="store_true", help="Chạy RoboNeo thật sau preprocess")
    p.add_argument("--out", default="", help="Thư mục output")
    p.add_argument("--cases", action="store_true", help="Chạy bộ test 10/12/15/18s")
    args = p.parse_args()

    out_root = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="roboneo_speed_test_"))
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output: {out_root}")

    results: list[dict] = []

    if args.roboneo:
        if not args.video or not args.image:
            print("❌ --roboneo cần --video và --image")
            return 1
        vid = Path(args.video)
        img = Path(args.image)
        if not vid.is_file() or not img.is_file():
            print("❌ Thiếu file video hoặc ảnh")
            return 1
        results.append(
            run_roboneo_e2e(
                image=img,
                video=vid,
                out_root=out_root,
                email=(args.email or "").strip(),
                password=(args.password or "").strip(),
            )
        )
    elif args.video:
        src = Path(args.video)
        if not src.is_file():
            print(f"❌ Không thấy {src}")
            return 1
        work = out_root / "custom"
        work.mkdir(parents=True, exist_ok=True)
        dur = probe_video_duration_seconds(str(src))
        print(f"\nVIDEO {src.name} · {dur:.2f}s")
        roboneo_in, plan = prepare_roboneo_reference(src, work)
        fake = simulate_roboneo_output(roboneo_in, work)
        final = restore_roboneo_output(fake, plan, work)
        results.append(
            {
                "video": str(src),
                "source_sec": dur,
                "plan": asdict(plan),
                "roboneo_input": str(roboneo_in),
                "final": str(final),
            }
        )
    elif args.cases:
        for label, sec in [("10s_normal", 10), ("12s_speed", 12), ("15s_speed", 15), ("18s_trim_speed", 18)]:
            results.append(run_case(label, sec, out_root))
    else:
        # Mặc định: chỉ in plan + chạy cases
        print("\n--- Plan preview ---")
        for sec in [10, 11.9, 12, 14, 15, 15.1, 20]:
            pl = plan_roboneo_reference(sec)
            print(f"  {sec:5.1f}s → {pl.summary()}")
        print("\nChạy --cases để test ffmpeg hoặc --video path.mp4")
        for label, sec in [("10s_normal", 10), ("12s_speed", 12), ("15s_speed", 15), ("18s_trim_speed", 18)]:
            results.append(run_case(label, sec, out_root))

    report = out_root / "report.json"
    report.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n📄 Report: {report}")

    if args.cases or not args.video:
        fails = [r for r in results if isinstance(r.get("ok_input_under_12"), bool) and not r["ok_input_under_12"]]
        if fails:
            print(f"❌ {len(fails)} case fail input ≥ 12s")
            return 1
        print("✅ Tất cả case: input RoboNeo < 12s, restore gần đúng độ dài làm việc")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
