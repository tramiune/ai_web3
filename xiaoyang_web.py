"""
XiaoYang web session — motionai (web1): cookie login, không API v1 key.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

import requests

from project_env import get_env, load_project_env

load_project_env()
XIAOYANG_ORIGIN = get_env("XIAOYANG_ORIGIN", "https://xiaoyang.online").rstrip("/")

MOTION_V26 = "motion_v26"
MOTION_V30 = "motion_v30"


class XiaoyangWebError(RuntimeError):
    pass


class XiaoyangAuthError(XiaoyangWebError):
    pass


def session_file_for_account(account_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9_-]", "_", (account_id or "default").lower())
    return Path(__file__).resolve().parent / f"xiaoyang_session_{safe}.json"


class XiaoyangWebClient:
    def __init__(self, account_id: str = "default", session: requests.Session | None = None):
        load_project_env()
        self.account_id = account_id
        self.session_file = session_file_for_account(account_id)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": get_env(
                    "XIAOYANG_USER_AGENT",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
                "Accept": "application/json",
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                "Origin": XIAOYANG_ORIGIN,
                "Referer": f"{XIAOYANG_ORIGIN}/",
            }
        )
        self._load_cookies()

    def _url(self, path: str) -> str:
        return f"{XIAOYANG_ORIGIN}{path if path.startswith('/') else '/' + path}"

    def _save_cookies(self) -> None:
        data = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.session.cookies
        ]
        self.session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_cookies(self) -> None:
        if not self.session_file.is_file():
            return
        try:
            for item in json.loads(self.session_file.read_text(encoding="utf-8")):
                self.session.cookies.set(
                    item["name"],
                    item["value"],
                    domain=item.get("domain"),
                    path=item.get("path", "/"),
                )
        except Exception:
            pass

    def _request(self, method: str, path: str, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 120)
        r = self.session.request(method, self._url(path), timeout=timeout, **kwargs)
        if r.status_code == 401:
            raise XiaoyangAuthError("Session hết hạn — login lại")
        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {"detail": (r.text or "")[:500]}
        if not r.ok:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise XiaoyangWebError(f"HTTP {r.status_code}: {detail or (r.text or '')[:300]}")
        return data if isinstance(data, dict) else {"data": data}

    def login(self, email: str | None = None, password: str | None = None) -> dict:
        email = (email or get_env("XIAOYANG_EMAIL")).strip()
        password = password or get_env("XIAOYANG_PASSWORD")
        if not email or not password:
            raise XiaoyangAuthError("Thiếu XIAOYANG_EMAIL / XIAOYANG_PASSWORD")
        data = self._request(
            "POST",
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"},
        )
        self._save_cookies()
        return data

    def me(self) -> dict:
        return self._request("GET", "/api/auth/me")

    def upload_file(self, file_path: str) -> str:
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            raise XiaoyangWebError(f"File không tồn tại: {file_path}")
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        name = os.path.basename(file_path)
        timeout = int(get_env("XIAOYANG_UPLOAD_TIMEOUT_SEC", "300"))
        retries = int(get_env("XIAOYANG_UPLOAD_RETRIES", "3"))
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                with open(file_path, "rb") as f:
                    payload = f.read()
                r = self.session.post(
                    self._url("/api/upload"),
                    files={"file": (name, payload, mime)},
                    headers={"Connection": "close"},
                    timeout=timeout,
                )
                if r.status_code == 401:
                    raise XiaoyangAuthError("Session hết hạn khi upload")
                body = r.json() if r.content else {}
                if not r.ok:
                    raise XiaoyangWebError(
                        f"Upload HTTP {r.status_code}: {body.get('detail', r.text[:200])}"
                    )
                token = body.get("token")
                if not token:
                    raise XiaoyangWebError(f"Upload không trả token: {body}")
                return str(token)
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
                last_err = e
                if attempt < retries:
                    wait = min(8, attempt * 2)
                    print(f"⚠️ Upload {name} lỗi SSL/mạng (lần {attempt}/{retries}), thử lại sau {wait}s...")
                    time.sleep(wait)
                    continue
                raise
        raise XiaoyangWebError(f"Upload thất bại: {last_err}")

    def create_motion_task(
        self,
        *,
        image_token: str,
        video_token: str,
        prompt: str = "",
        modal_key: str = MOTION_V26,
        option_key: str = "default",
        motion_orientation: str = "video",
        enhance_4k: bool = True,
    ) -> dict:
        body = {
            "modal_key": modal_key,
            "option_key": option_key,
            "prompt": (prompt or get_env("XIAOYANG_PROMPT", "Follow the reference motion naturally")).strip(),
            "image_token": image_token,
            "video_token": video_token,
            "motion_orientation": motion_orientation,
            "enhance_4k": bool(enhance_4k),
        }
        return self._request(
            "POST",
            "/api/tasks",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=int(get_env("XIAOYANG_CREATE_TIMEOUT_SEC", "120")),
        )

    def get_task(self, task_id: str) -> dict:
        try:
            return self._request("POST", f"/api/tasks/{task_id}/refresh")
        except XiaoyangWebError:
            data = self._request("GET", "/api/tasks")
            for t in data.get("tasks") or []:
                if str(t.get("task_id")) == str(task_id):
                    return t
            raise

    def download_task_file(self, task_id: str, dest_path: str) -> str:
        dest_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with self.session.get(
            self._url(f"/api/tasks/{task_id}/file"),
            stream=True,
            timeout=int(get_env("XIAOYANG_DOWNLOAD_TIMEOUT_SEC", "600")),
        ) as r:
            if r.status_code == 401:
                raise XiaoyangAuthError("Session hết hạn khi tải video")
            if not r.ok:
                raise XiaoyangWebError(f"Download HTTP {r.status_code}: {(r.text or '')[:300]}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest_path
