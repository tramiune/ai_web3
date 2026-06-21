"""
Video AI Easy (videoaieasy.hdgr.online) — web session cho kaling (web3) bot.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from project_env import get_env, load_project_env

load_project_env()

ORIGIN = get_env("VIDEOAIEASY_ORIGIN", "https://videoaieasy.hdgr.online").rstrip("/")
SUPABASE_URL = get_env(
    "VIDEOAIEASY_SUPABASE_URL", "https://gfevyulgkydodmlfnquh.supabase.co"
).rstrip("/")
SUPABASE_ANON_KEY = get_env(
    "VIDEOAIEASY_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdmZXZ5dWxna3lkb2RtbGZucXVoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA0MTA2MjEsImV4cCI6MjA5NTk4NjYyMX0.8jSdH2RuxZnRUxHPI2MUSNvdx15A5ZfzE9kqT1YvfF0",
)
AUTH_COOKIE = "sb-gfevyulgkydodmlfnquh-auth-token"

MODEL_KLING_26 = "kling-2.6"
MODEL_KLING_30 = "kling-3.0"
QUALITY_MODEL_IDS = frozenset({"127"})
KALING_TURBO_MODEL_IDS = frozenset({"117"})
KALING_VAE_10_MODEL_IDS = frozenset({"124"})
KALING_VAE_20_MODEL_IDS = frozenset({"125"})
KALING_VAE_1080_10_MODEL_IDS = frozenset({"126"})
KALING_VAE_1080_20_MODEL_IDS = frozenset({"128"})
KALING_VAE_1080_30_MODEL_IDS = frozenset({"129"})
KALING_VAE_1080_MODEL_IDS = (
    KALING_VAE_1080_10_MODEL_IDS
    | KALING_VAE_1080_20_MODEL_IDS
    | KALING_VAE_1080_30_MODEL_IDS
)
VAE_PACKAGE_10_DURATION_SEC = 10
VAE_PACKAGE_15_DURATION_SEC = 15
VAE_PACKAGE_20_DURATION_SEC = 20
VAE_PACKAGE_30_DURATION_SEC = 30
VAE_CREDITS_BY_DURATION = {10: 1, 15: 2, 20: 2, 30: 3}
VAE_CREDITS_1080_BY_DURATION = {10: 2, 20: 4, 30: 6}
# VAE API: 10 coins = 1 xu (profile.coins)
VAE_COINS_720P_BY_DURATION = {10: 10, 15: 15, 20: 20, 30: 30}
VAE_COINS_1080P_BY_DURATION = {10: 20, 20: 40, 30: 60}
VAE_API_MODEL_WEAVY = "weavy-kling-26"
VAE_API_MODEL_MOTION_1080P = "pixverse"
VAE_MAX_UPLOAD_BYTES = int(get_env("VIDEOAIEASY_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
DEFAULT_VAE_RESOLUTION = "720p"


class VideoAiEasyError(RuntimeError):
    pass


class VideoAiEasyCreditError(VideoAiEasyError):
    """Nick VAE không đủ coin/xu cho job."""


class VideoAiEasyAuthError(VideoAiEasyError):
    pass


def session_file_for_account(account_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]", "_", (account_id or "default").lower())
    return Path(__file__).resolve().parent / f"videoaieasy_session_{safe}.json"


def _encode_supabase_cookie(session: dict) -> str:
    payload = {
        "access_token": session["access_token"],
        "token_type": session.get("token_type", "bearer"),
        "expires_in": session.get("expires_in", 3600),
        "expires_at": session.get("expires_at"),
        "refresh_token": session.get("refresh_token"),
        "user": session.get("user"),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return "base64-" + base64.b64encode(raw).decode("ascii")


class VideoAiEasyClient:
    def __init__(self, account_id: str = "default", session: requests.Session | None = None):
        self.account_id = account_id
        self.session_file = session_file_for_account(account_id)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": get_env(
                    "VIDEOAIEASY_USER_AGENT",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
                "Accept": "application/json",
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/dashboard",
            }
        )
        self._user_email: str | None = None
        self._load_session()

    def _save_session(self) -> None:
        data = {
            "cookie_name": AUTH_COOKIE,
            "cookie_value": self.session.cookies.get(AUTH_COOKIE, ""),
            "email": self._user_email,
        }
        self.session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_session(self) -> None:
        if not self.session_file.is_file():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            name = data.get("cookie_name") or AUTH_COOKIE
            value = data.get("cookie_value") or ""
            if value:
                self.session.cookies.set(name, value, domain="videoaieasy.hdgr.online", path="/")
            self._user_email = data.get("email")
        except Exception:
            pass

    def _api(self, method: str, path: str, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 120)
        url = f"{ORIGIN}{path if path.startswith('/') else '/' + path}"
        r = self.session.request(method, url, timeout=timeout, **kwargs)
        if r.status_code == 401:
            raise VideoAiEasyAuthError("Session hết hạn — login lại")
        if r.status_code == 403:
            raise VideoAiEasyAuthError("Session không hợp lệ — login lại")
        try:
            body = r.json() if r.content else {}
        except Exception:
            body = {"error": (r.text or "")[:500]}
        if not r.ok:
            err = body.get("error") if isinstance(body, dict) else None
            raise VideoAiEasyError(f"HTTP {r.status_code}: {err or (r.text or '')[:300]}")
        if isinstance(body, dict) and body.get("ok") is False:
            raise VideoAiEasyError(body.get("error") or "API lỗi")
        return body if isinstance(body, dict) else {"data": body}

    def login(self, email: str | None = None, password: str | None = None) -> dict:
        email = (email or get_env("VIDEOAIEASY_EMAIL") or "").strip()
        password = password or get_env("VIDEOAIEASY_PASSWORD")
        if not email or not password:
            raise VideoAiEasyAuthError("Thiếu VIDEOAIEASY_EMAIL / VIDEOAIEASY_PASSWORD")
        r = requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=30,
        )
        if r.status_code != 200:
            detail = r.json().get("error_description") if r.content else r.text
            raise VideoAiEasyAuthError(f"Login thất bại: {detail or r.status_code}")
        sess = r.json()
        cookie_val = _encode_supabase_cookie(sess)
        self.session.cookies.set(AUTH_COOKIE, cookie_val, domain="videoaieasy.hdgr.online", path="/")
        self._user_email = email
        self._save_session()
        return sess

    def _probe_origin_session(self) -> None:
        """Origin /api/* can reject cookies while Supabase profile still looks valid."""
        self._api("GET", "/api/jobs", params={"limit": 1}, timeout=30)

    def ensure_session(self, email: str | None = None, password: str | None = None) -> dict:
        email = (email or self._user_email or get_env("VIDEOAIEASY_EMAIL") or "").strip()
        password = password or get_env("VIDEOAIEASY_PASSWORD")
        try:
            self._probe_origin_session()
            return self.get_profile()
        except (VideoAiEasyAuthError, VideoAiEasyError, ValueError, json.JSONDecodeError):
            pass
        except Exception as e:
            if "padding" not in str(e).lower() and "base64" not in str(e).lower():
                raise
        self.login(email, password)
        self._probe_origin_session()
        return self.get_profile()

    def get_profile(self) -> dict:
        me = self._current_user()
        uid = me["id"]
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles?select=*&id=eq.{uid}",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {self._access_token()}",
            },
            timeout=30,
        )
        if r.status_code == 401:
            raise VideoAiEasyAuthError("Token hết hạn")
        rows = r.json() if r.content else []
        if not rows:
            raise VideoAiEasyError("Không tìm thấy profile")
        return rows[0]

    def _access_token(self) -> str:
        raw = self.session.cookies.get(AUTH_COOKIE, "")
        if not raw.startswith("base64-"):
            raise VideoAiEasyAuthError("Chưa có session cookie")
        payload = json.loads(base64.b64decode(raw[7:]).decode("utf-8"))
        token = payload.get("access_token")
        if not token:
            raise VideoAiEasyAuthError("Cookie không có access_token")
        return token

    def _current_user(self) -> dict:
        raw = self.session.cookies.get(AUTH_COOKIE, "")
        if not raw.startswith("base64-"):
            raise VideoAiEasyAuthError("Chưa đăng nhập")
        payload = json.loads(base64.b64decode(raw[7:]).decode("utf-8"))
        user = payload.get("user") or {}
        if not user.get("id"):
            raise VideoAiEasyAuthError("Cookie không hợp lệ")
        return user

    def upload_file(self, file_path: str, *, kind: str | None = None) -> str:
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            raise VideoAiEasyError(f"File không tồn tại: {file_path}")
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if kind is None:
            kind = "video" if mime.startswith("video/") else "image"
        with open(file_path, "rb") as f:
            payload = f.read()
        info = self._api(
            "POST",
            "/api/upload",
            json={
                "kind": kind,
                "fileName": os.path.basename(file_path),
                "contentType": mime,
                "fileSize": len(payload),
            },
            headers={"Content-Type": "application/json"},
        )["data"]
        upload_url = (info.get("uploadUrl") or "").replace("\n", "").replace("\r", "").strip()
        public_url = re.sub(r"\s+", "", info.get("publicUrl") or "")
        timeout = int(get_env("VIDEOAIEASY_UPLOAD_TIMEOUT_SEC", "300"))
        r = requests.put(upload_url, data=payload, headers={"Content-Type": mime}, timeout=timeout)
        if not r.ok:
            raise VideoAiEasyError(f"Upload R2 HTTP {r.status_code}: {(r.text or '')[:200]}")
        if not public_url:
            raise VideoAiEasyError("Upload không trả publicUrl")
        return public_url

    def create_motion_job(
        self,
        *,
        input_image_url: str,
        driving_video_url: str,
        prompt: str = "",
        model_id: str = MODEL_KLING_26,
        resolution: str | None = None,
        duration_sec: int | None = None,
        api_model: str | None = None,
    ) -> str:
        res = normalize_vae_resolution(resolution)
        dur = normalize_vae_duration_sec(duration_sec)
        vae_model = (api_model or model_id or MODEL_KLING_26).strip()
        body = {
            "mode": "motion-control",
            "modelId": vae_model,
            "prompt": (prompt or get_env(
                "VIDEOAIEASY_PROMPT", "Follow the reference motion naturally"
            )).strip(),
            "inputImageUrl": input_image_url.strip(),
            "drivingVideoUrl": driving_video_url.strip(),
            "durationSec": dur,
        }
        # kling-2.6 (Pro): gửi resolution 720p. weavy-kling-26 (fallback 5 coin): không gửi resolution.
        if vae_model == MODEL_KLING_26:
            body["resolution"] = res
        elif vae_model == VAE_API_MODEL_MOTION_1080P:
            body["resolution"] = res
        resp = self._api(
            "POST",
            "/api/jobs",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=int(get_env("VIDEOAIEASY_CREATE_TIMEOUT_SEC", "120")),
        )
        return str(resp["data"]["jobId"])

    def get_job(self, job_id: str) -> dict:
        last_err = None
        retries = int(get_env("VIDEOAIEASY_GET_JOB_RETRIES", "3"))
        pause = int(get_env("VIDEOAIEASY_GET_JOB_RETRY_SEC", "3"))
        for attempt in range(1, retries + 1):
            try:
                return self._api("GET", f"/api/jobs/{job_id}")["data"]
            except VideoAiEasyError as e:
                last_err = e
                if attempt < retries and ("500" in str(e) or "502" in str(e) or "503" in str(e)):
                    time.sleep(pause * attempt)
                    continue
                raise
        raise last_err  # pragma: no cover

    def download_job(self, job_id: str, dest_path: str) -> str:
        dest_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        url = f"{ORIGIN}/api/download/{job_id}"
        with self.session.get(
            url,
            stream=True,
            timeout=int(get_env("VIDEOAIEASY_DOWNLOAD_TIMEOUT_SEC", "600")),
        ) as r:
            if r.status_code == 401:
                raise VideoAiEasyAuthError("Session hết hạn khi tải video")
            if not r.ok:
                raise VideoAiEasyError(f"Download HTTP {r.status_code}: {(r.text or '')[:300]}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest_path

    def try_delete_job(self, job_id: str) -> bool:
        """Xóa job trên VAE sau khi đã trả hàng Kaling (lỗi không chặn luồng chính)."""
        job_id = str(job_id or "").strip()
        if not job_id:
            return False
        try:
            self._api("DELETE", f"/api/jobs/{job_id}", timeout=30)
            print(f"🗑️ VideoAiEasy đã xóa job {job_id}")
            return True
        except VideoAiEasyAuthError as e:
            print(f"⚠️ VideoAiEasy delete job {job_id}: {e}")
            return False
        except VideoAiEasyError as e:
            err = str(e)
            if "404" in err:
                return True
            if "409" in err:
                print(f"⚠️ VideoAiEasy job {job_id} chưa xóa được: {e}")
                return False
            print(f"⚠️ VideoAiEasy delete job {job_id}: {e}")
            return False


def normalize_vae_resolution(value: str | None) -> str:
    raw = (value or get_env("VIDEOAIEASY_DEFAULT_RESOLUTION", DEFAULT_VAE_RESOLUTION)).strip().lower()
    if raw in ("1080", "1080p", "hd", "full_hd", "fullhd"):
        return "1080p"
    if raw in ("480", "480p"):
        return "480p"
    return "720p"


def resolution_for_order(order_data: dict | None) -> str:
    data = order_data or {}
    explicit = data.get("vaeResolution") or data.get("resolution") or data.get("videoResolution")
    if explicit:
        return normalize_vae_resolution(str(explicit))
    # Kaling: UI có thể ghi 1080p nhưng render thực luôn 720p.
    return normalize_vae_resolution(None)


def normalize_vae_duration_sec(value: int | float | str | None) -> int:
    """VAE: gói 10s, 20s hoặc 30s."""
    try:
        sec = int(float(value))
    except (TypeError, ValueError):
        return VAE_PACKAGE_10_DURATION_SEC
    if sec >= 25:
        return VAE_PACKAGE_30_DURATION_SEC
    if sec >= 20:
        return VAE_PACKAGE_20_DURATION_SEC
    if sec >= 15:
        return VAE_PACKAGE_15_DURATION_SEC
    return VAE_PACKAGE_10_DURATION_SEC


def vae_motion_api_model(resolution: str | None, *, weavy: bool = False) -> str:
    """weavy-kling-26 = fallback RoboNeo 5 coin. kling-2.6 = Pro 10 coin."""
    if weavy:
        return VAE_API_MODEL_WEAVY
    if normalize_vae_resolution(resolution) == "1080p":
        return VAE_API_MODEL_MOTION_1080P
    return MODEL_KLING_26


def vae_coins_for_duration(duration_sec: int, resolution: str | None = None) -> int:
    """Số coins VAE trừ (10 coins = 1 xu trên profile)."""
    dur = int(duration_sec)
    if normalize_vae_resolution(resolution) == "1080p":
        return VAE_COINS_1080P_BY_DURATION.get(dur, 20)
    return VAE_COINS_720P_BY_DURATION.get(dur, 10)


def vae_credits_for_duration(duration_sec: int, resolution: str | None = None) -> int:
    """Alias — trả coins VAE (không phải xu)."""
    return vae_coins_for_duration(duration_sec, resolution)


def vae_xu_for_duration(duration_sec: int, resolution: str | None = None) -> float:
    return vae_coins_for_duration(duration_sec, resolution) / 10.0


def profile_credits(profile: dict | None) -> int:
    if not profile:
        return 0
    for key in ("credits", "balance", "coin", "coins"):
        val = profile.get(key)
        if val is None:
            continue
        try:
            return max(0, int(val))
        except (TypeError, ValueError):
            pass
    return 0


def is_vae_credit_error(err: object) -> bool:
    if isinstance(err, VideoAiEasyCreditError):
        return True
    s = str(err or "").lower()
    return any(
        x in s
        for x in (
            "credit",
            "coin",
            "coins",
            "balance",
            "insufficient",
            "not enough",
            "không đủ",
            "hết coin",
            "hết xu",
            "402",
            "payment required",
        )
    )


def duration_for_order(order_data: dict | None) -> int:
    """Map đơn Kaling → gói VAE: 10s, 20s hoặc 30s."""
    from roboneo_trial import is_roboneo_trial_order

    data = order_data or {}
    for key in ("vaeDurationSec", "durationSec"):
        val = data.get(key)
        if val is not None:
            return normalize_vae_duration_sec(val)
    if is_roboneo_trial_order(data):
        # Gói thử RoboNeo 12s — fallback VAE dùng gói tiết kiệm 10s (1 xu).
        return VAE_PACKAGE_10_DURATION_SEC
    model_id = str(data.get("modelId") or "").strip()
    if model_id in KALING_VAE_1080_30_MODEL_IDS:
        return VAE_PACKAGE_30_DURATION_SEC
    if model_id in KALING_VAE_20_MODEL_IDS:
        return VAE_PACKAGE_15_DURATION_SEC
    if model_id in KALING_VAE_1080_20_MODEL_IDS:
        return VAE_PACKAGE_20_DURATION_SEC
    if model_id in KALING_VAE_1080_10_MODEL_IDS or model_id in KALING_VAE_10_MODEL_IDS:
        return VAE_PACKAGE_10_DURATION_SEC
    return VAE_PACKAGE_10_DURATION_SEC


def _parse_vae_aspect_ratio(aspect_ratio: str | None) -> float:
    raw = (aspect_ratio or get_env("VIDEOAIEASY_IMAGE_ASPECT", "9:16")).strip().lower()
    if raw in ("9:16", "vertical", "portrait", "dọc"):
        return 9 / 16
    if raw in ("16:9", "horizontal", "landscape", "ngang"):
        return 16 / 9
    if ":" in raw:
        left, right = raw.split(":", 1)
        try:
            a, b = float(left), float(right)
            if a > 0 and b > 0:
                return a / b
        except ValueError:
            pass
    return 9 / 16


def prepare_character_image_for_vae(
    image_path: str,
    *,
    aspect_ratio: str | None = None,
) -> tuple[str, bool]:
    """Pad đen (letterbox/pillarbox) + resize trước upload VideoAiEasy."""
    try:
        from PIL import Image
    except ImportError as e:
        raise VideoAiEasyError(
            "Thiếu Pillow — cài: pip install Pillow"
        ) from e

    import tempfile

    max_long = int(get_env("VIDEOAIEASY_IMAGE_MAX_LONG_EDGE", "2752"))
    ratio_tol = float(get_env("VIDEOAIEASY_IMAGE_RATIO_TOLERANCE", "0.015"))
    jpeg_q = int(get_env("VIDEOAIEASY_IMAGE_JPEG_QUALITY", "92"))

    image_path = os.path.abspath(image_path)
    if not os.path.isfile(image_path):
        raise VideoAiEasyError(f"File không tồn tại: {image_path}")

    target = _parse_vae_aspect_ratio(aspect_ratio)
    with Image.open(image_path) as opened:
        img = opened.convert("RGB")
    orig_w, orig_h = img.size
    current = orig_w / orig_h if orig_h else target

    needs_pad = abs(current - target) / target > ratio_tol
    needs_resize = max(orig_w, orig_h) > max_long
    if not needs_pad and not needs_resize:
        return image_path, False

    if needs_pad:
        if current > target:
            canvas_w, canvas_h = orig_w, max(1, int(round(orig_w / target)))
        else:
            canvas_h, canvas_w = orig_h, max(1, int(round(orig_h * target)))
        canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
        canvas.paste(img, ((canvas_w - orig_w) // 2, (canvas_h - orig_h) // 2))
        img = canvas

    w, h = img.size
    if max(w, h) > max_long:
        scale = max_long / max(w, h)
        img = img.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.Resampling.LANCZOS,
        )

    out_w, out_h = img.size
    fd, out_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    img.save(out_path, format="JPEG", quality=jpeg_q)
    ar_label = aspect_ratio or get_env("VIDEOAIEASY_IMAGE_ASPECT", "9:16")
    print(
        f"🖼️ VAE ảnh {orig_w}×{orig_h} → {out_w}×{out_h} "
        f"(pad đen + resize, tỉ lệ {ar_label})"
    )
    return out_path, True


def _ffmpeg_bin() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil

        return shutil.which("ffmpeg")


def prepare_motion_video_for_vae_upload(
    source_path: str,
    *,
    max_seconds: float | None = None,
    max_bytes: int | None = None,
) -> tuple[str, bool]:
    """Cắt video về đúng gói 10/20/30s trước upload — VAE tính xu theo video thật, không chỉ durationSec API."""
    src = Path(source_path)
    if not src.is_file():
        raise VideoAiEasyError(f"File không tồn tại: {source_path}")

    limit = max_bytes if max_bytes is not None else VAE_MAX_UPLOAD_BYTES
    ffmpeg = _ffmpeg_bin()
    work_path = src
    work_tmp = False

    if max_seconds is not None and max_seconds > 0 and ffmpeg:
        fd, outp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        trim_out = Path(outp)
        cmd = [
            ffmpeg, "-y", "-i", str(work_path),
            "-t", str(max_seconds),
            "-c", "copy", "-movflags", "+faststart", str(trim_out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            cmd = [
                ffmpeg, "-y", "-i", str(work_path),
                "-t", str(max_seconds),
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                str(trim_out),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and trim_out.is_file():
            if work_tmp and work_path != src:
                try:
                    work_path.unlink()
                except OSError:
                    pass
            work_path = trim_out
            work_tmp = True
            print(f"✂️ Cắt video motion → {max_seconds}s (VAE gói {int(max_seconds)}s)")
        elif max_seconds is not None:
            raise VideoAiEasyError(
                f"Không cắt được video về {max_seconds}s — VAE sẽ tính xu theo video dài hơn gói"
            )
    elif max_seconds is not None and max_seconds > 0 and not ffmpeg:
        raise VideoAiEasyError("Thiếu ffmpeg — không cắt video VAE theo gói được")

    size = work_path.stat().st_size
    if size <= limit:
        return str(work_path), work_tmp

    if not ffmpeg:
        raise VideoAiEasyError(
            f"Video {size / (1024 * 1024):.1f}MB > giới hạn VAE "
            f"{limit / (1024 * 1024):.0f}MB — cần ffmpeg để nén"
        )

    mb = size / (1024 * 1024)
    print(f"📦 Video {mb:.1f}MB > {limit / (1024 * 1024):.0f}MB — nén trước upload VAE...")
    for crf in (28, 32, 36):
        fd, outp = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        out_path = Path(outp)
        cmd = [ffmpeg, "-y", "-i", str(work_path)]
        if max_seconds is not None and max_seconds > 0:
            cmd.extend(["-t", str(max_seconds)])
        cmd.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            str(out_path),
        ])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out_path.is_file():
            continue
        if out_path.stat().st_size <= limit:
            if work_tmp and work_path != src:
                try:
                    work_path.unlink()
                except OSError:
                    pass
            print(f"✅ Nén VAE OK (crf {crf}) → {out_path.stat().st_size / (1024 * 1024):.1f}MB")
            return str(out_path), True
        try:
            out_path.unlink()
        except OSError:
            pass

    raise VideoAiEasyError(
        f"Video vẫn > {limit / (1024 * 1024):.0f}MB sau khi nén — chọn video ngắn/nhẹ hơn"
    )
