"""Chuẩn bị / khôi phục video tham chiếu RoboNeo (giới hạn input <12s)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from tool98_api import probe_video_duration_seconds, trim_video_to_seconds

ROBONEO_INPUT_MAX_SEC = 12.0
ROBONEO_SPEED_TARGET_SEC = 11.5
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

    def to_dict(self) -> dict:
        return asdict(self)


def plan_from_dict(data: dict | None) -> RoboNeoRefPlan | None:
    if not data:
        return None
    try:
        return RoboNeoRefPlan(
            branch=str(data.get("branch") or "normal"),
            source_sec=float(data.get("source_sec") or 0),
            trim_to_sec=(
                float(data["trim_to_sec"])
                if data.get("trim_to_sec") is not None
                else None
            ),
            work_sec=float(data.get("work_sec") or 0),
            speed_factor=float(data.get("speed_factor") or 1.0),
            roboneo_input_target_sec=float(data.get("roboneo_input_target_sec") or 0),
            restore_factor=float(data.get("restore_factor") or 1.0),
        )
    except (TypeError, ValueError):
        return None


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
    if factor <= 1.0 + 1e-6:
        shutil.copy2(source, output)
        return output
    ff = _ffmpeg()
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


def prepare_roboneo_reference(
    source: Path,
    work_dir: Path,
    *,
    log: bool = True,
) -> tuple[Path, RoboNeoRefPlan]:
    dur = probe_video_duration_seconds(str(source))
    if dur is None:
        raise RuntimeError(f"Không đọc được duration: {source}")
    plan = plan_roboneo_reference(dur)
    if log:
        print(f"📋 RoboNeo ref: {plan.summary()}")

    current = source
    if plan.trim_to_sec is not None:
        trimmed = work_dir / f"trim_{plan.trim_to_sec:.0f}s{source.suffix or '.mp4'}"
        current = Path(
            trim_video_to_seconds(current, max_seconds=plan.trim_to_sec, output=trimmed)
        )
        if log:
            td = probe_video_duration_seconds(str(current))
            print(f"   ✂️ trim đầu → {td:.2f}s ({trimmed.name})")

    if plan.branch == "speed_up":
        sped = work_dir / f"speed_x{plan.speed_factor:.3f}{source.suffix or '.mp4'}"
        speed_up_video(current, factor=plan.speed_factor, output=sped)
        if log:
            sd = probe_video_duration_seconds(str(sped))
            print(f"   ⚡ speed-up → {sd:.2f}s ({sped.name})")
            if sd is not None and sd >= ROBONEO_INPUT_MAX_SEC - 0.05:
                print(f"   ⚠️ vẫn ≥ {ROBONEO_INPUT_MAX_SEC}s — cần hạ target hoặc tăng factor")
        return sped, plan

    return current, plan


def restore_roboneo_output(
    roboneo_output: Path,
    plan: RoboNeoRefPlan,
    work_dir: Path,
    *,
    log: bool = True,
) -> Path:
    if plan.branch == "normal":
        return roboneo_output
    out = work_dir / f"restored{roboneo_output.suffix or '.mp4'}"
    slow_down_video(roboneo_output, factor=plan.restore_factor, output=out)
    if log:
        od = probe_video_duration_seconds(str(out))
        print(f"   🐢 restore speed → {od:.2f}s ({out.name})")
    return out
