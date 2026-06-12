"""
Video AI Easy (videoaieasy.hdgr.online) — web session cho kaling (web3) bot.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
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


class VideoAiEasyError(RuntimeError):
    pass


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
        except (VideoAiEasyAuthError, VideoAiEasyError):
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
    ) -> str:
        body = {
            "mode": "motion-control",
            "modelId": model_id,
            "prompt": (prompt or get_env(
                "VIDEOAIEASY_PROMPT", "Follow the reference motion naturally"
            )).strip(),
            "inputImageUrl": input_image_url.strip(),
            "drivingVideoUrl": driving_video_url.strip(),
        }
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
