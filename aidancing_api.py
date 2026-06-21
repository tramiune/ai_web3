"""Aidancing.net — Pure HTTP client (requests + session cookie).

Cấu hình sau (một trong hai):
  export AIDANCING_COOKIE='JSESSIONID=...'
  hoặc file .env: AIDANCING_COOKIE=JSESSIONID=...
"""

from __future__ import annotations

import mimetypes
import os
import re
import time
from pathlib import Path

import requests

AIDANCING_ORIGIN = os.environ.get("AIDANCING_ORIGIN", "https://aidancing.net")
DASHBOARD_URL = f"{AIDANCING_ORIGIN}/dashboard"


class SessionExpiredError(RuntimeError):
    """Cookie/JSESSIONID hết hạn hoặc không hợp lệ."""


def parse_balance_from_dashboard_html(html: str) -> float | None:
    """Đọc số credit header dashboard (span.cp-balance > span)."""
    text = html or ""
    if "accounts.google.com" in text and "cp-balance" not in text:
        return None
    for pat in (
        r'class="cp-balance"[^>]*>\s*<span>\s*([\d]+(?:\.\d+)?)\s*</span>',
        r'cp-balance[\s\S]{0,120}?<span>\s*([\d]+(?:\.\d+)?)\s*</span>',
        r'"balance"\s*:\s*([\d.]+)',
        r'"coinBalance"\s*:\s*([\d.]+)',
        r'"coins"\s*:\s*([\d.]+)',
    ):
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = float(m.group(1))
                if 0 <= val < 1_000_000:
                    return val
            except ValueError:
                pass
    return None


def load_cookie() -> str:
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("AIDANCING_COOKIE="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    cookie = os.environ.get("AIDANCING_COOKIE", "").strip()
    if cookie:
        return cookie
    jsession = os.environ.get("JSESSIONID", "").strip()
    if jsession:
        return f"JSESSIONID={jsession}"
    raise ValueError(
        "Thiếu AIDANCING_COOKIE hoặc JSESSIONID. "
        "Copy Cookie từ DevTools (request /api/proxy/jobs) vào .env"
    )


class AidancingApiClient:
    """Gọi API aidancing qua HTTP — không cần trình duyệt."""

    def __init__(self, cookie: str | None = None):
        self._cookie = (cookie or load_cookie()).strip()
        if not self._cookie:
            raise ValueError("AIDANCING_COOKIE is empty")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": os.environ.get(
                    "AIDANCING_USER_AGENT",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
                "Accept": "*/*",
                "Origin": AIDANCING_ORIGIN,
                "Referer": DASHBOARD_URL,
                "Cookie": self._cookie,
            }
        )

    @staticmethod
    def _check_auth(response: requests.Response) -> None:
        if response.status_code in (401, 403):
            raise SessionExpiredError(
                "Session expired or unauthorized — cập nhật AIDANCING_COOKIE trong .env"
            )

    def list_jobs(self, page: int = 0, size: int = 50) -> dict:
        url = f"{AIDANCING_ORIGIN}/api/proxy/jobs"
        r = self.session.get(url, params={"page": page, "size": size}, timeout=60)
        self._check_auth(r)
        r.raise_for_status()
        return r.json()

    def get_balance(self) -> float:
        """Số credit/coin trên dashboard — GET /dashboard + parse cp-balance."""
        self.list_jobs(page=0, size=1)
        r = self.session.get(DASHBOARD_URL, timeout=30)
        self._check_auth(r)
        if r.status_code in (401, 403):
            raise SessionExpiredError(
                "Session expired or unauthorized — cập nhật AIDANCING_COOKIE trong .env"
            )
        r.raise_for_status()
        bal = parse_balance_from_dashboard_html(r.text or "")
        if bal is None:
            raise RuntimeError("Session OK — không đọc coin từ dashboard HTML")
        return bal

    def find_job(self, job_id) -> dict | None:
        found = self.find_jobs_by_ids([job_id])
        return found.get(int(job_id))

    def find_jobs_by_ids(self, job_ids) -> dict[int, dict]:
        wanted = {int(j) for j in job_ids if j}
        found: dict[int, dict] = {}
        if not wanted:
            return found
        for p in range(3):
            data = self.list_jobs(page=p, size=50)
            for item in data.get("items", []):
                jid = int(item.get("id", 0))
                if jid in wanted:
                    found[jid] = item
            if len(found) == len(wanted):
                break
        return found

    def create_job(
        self,
        model_id,
        image_path,
        video_path,
        quality_mode: str = "2",
        aspect_ratio: str = "9:16",
        title: str = "MotionAI Bot",
    ) -> str:
        image_path = os.path.abspath(image_path)
        video_path = os.path.abspath(video_path)
        if not os.path.isfile(image_path):
            raise RuntimeError(f"File không tồn tại: {image_path}")
        if not os.path.isfile(video_path):
            raise RuntimeError(f"File không tồn tại: {video_path}")

        before_ids = {
            int(j["id"]) for j in self.list_jobs(page=0, size=30).get("items", [])
        }

        data = {
            "jobTypeId": str(model_id),
            "aspectRatio": aspect_ratio,
            "qualityMode": str(quality_mode),
            "title": title,
            "userPrompt": "",
            "voiceId": "",
        }
        img_mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        vid_mime = mimetypes.guess_type(video_path)[0] or "video/mp4"

        with open(image_path, "rb") as img, open(video_path, "rb") as vid:
            files = {
                "image": (os.path.basename(image_path), img, img_mime),
                "video": (os.path.basename(video_path), vid, vid_mime),
            }
            r = self.session.post(
                f"{AIDANCING_ORIGIN}/create/general",
                data=data,
                files=files,
                timeout=int(os.environ.get("BOT_CREATE_TIMEOUT_SEC", "600")),
                allow_redirects=False,
            )

        if r.status_code not in (200, 302):
            raise RuntimeError(
                f"Create job failed: HTTP {r.status_code}\n{(r.text or '')[:500]}"
            )

        wait_sec = int(os.environ.get("BOT_CREATE_JOB_APPEAR_SEC", "36"))
        step = int(os.environ.get("BOT_CREATE_JOB_POLL_SEC", "3"))
        for _ in range(max(1, wait_sec // step)):
            time.sleep(step)
            for item in self.list_jobs(page=0, size=30).get("items", []):
                jid = int(item.get("id", 0))
                if jid not in before_ids:
                    return str(jid)

        raise RuntimeError("Đã submit nhưng không thấy job mới trên API")

    def download_file(self, file_id, dest_path) -> str:
        file_id = str(file_id).split("/")[-1]
        url = f"{AIDANCING_ORIGIN}/api/proxy/files/{file_id}"
        dest_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with self.session.get(url, stream=True, timeout=600) as r:
            self._check_auth(r)
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest_path
