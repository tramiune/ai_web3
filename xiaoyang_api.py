"""XiaoYang (xiaoyang.online) — Public API v1 client.

Cấu hình:
  export XIAOYANG_API_KEY='xy_...'
  hoặc .env: XIAOYANG_API_KEY=xy_...
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from xiaoyang_media import (
    MediaValidationError,
    is_workers_query_url,
    normalize_public_media_url,
    validate_motion_media,
)

XIAOYANG_ORIGIN = os.environ.get("XIAOYANG_ORIGIN", "https://xiaoyang.online").rstrip("/")


class XiaoyangAuthError(RuntimeError):
    """API key thiếu, sai hoặc bị khóa."""


class XiaoyangApiError(RuntimeError):
    """Lỗi HTTP / business từ API (402 hết credit, 400 tham số, ...)."""


def _split_api_keys(raw: str) -> list[str]:
    return [k.strip() for k in (raw or "").split(",") if k.strip()]


def load_api_keys() -> list[str]:
    """Danh sách key — XIAOYANG_API_KEYS (ưu tiên) hoặc XIAOYANG_API_KEY đơn."""
    env_file = Path(__file__).resolve().parent / ".env"
    keys_raw = os.environ.get("XIAOYANG_API_KEYS", "").strip()
    single = os.environ.get("XIAOYANG_API_KEY", "").strip()
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("XIAOYANG_API_KEYS="):
                keys_raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("XIAOYANG_API_KEY=") and not single:
                single = line.split("=", 1)[1].strip().strip('"').strip("'")
    keys = _split_api_keys(keys_raw)
    if keys:
        return keys
    if single:
        return [single]
    raise ValueError(
        "Thiếu XIAOYANG_API_KEYS hoặc XIAOYANG_API_KEY. "
        "Tạo key tại https://xiaoyang.online/api rồi ghi vào .env"
    )


def load_api_key() -> str:
    """Key mặc định (key đầu) — bot routing multi-key sẽ dùng load_api_keys()."""
    return load_api_keys()[0]


class XiaoyangApiClient:
    """Gọi https://xiaoyang.online/api/v1/* qua Bearer API key."""

    def __init__(self, api_key: str | None = None):
        self._api_key = (api_key or load_api_key()).strip()
        if not self._api_key:
            raise ValueError("XIAOYANG_API_KEY is empty")
        self.session = requests.Session()
        if os.environ.get("XIAOYANG_NO_PROXY", "").strip().lower() in ("1", "true", "yes"):
            self.session.trust_env = False
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                "User-Agent": os.environ.get(
                    "XIAOYANG_USER_AGENT",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
            }
        )

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{XIAOYANG_ORIGIN}{path}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 60)
        retries = int(os.environ.get("XIAOYANG_API_RETRIES", "5"))
        retry_wait = float(os.environ.get("XIAOYANG_API_RETRY_SEC", "8"))
        retryable = {502, 503, 504}
        last_err: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                r = self.session.request(method, self._url(path), timeout=timeout, **kwargs)
            except requests.RequestException as e:
                last_err = e
                if attempt < retries:
                    print(
                        f"  [XiaoYang] {method} {path} lỗi mạng ({e!s}) — "
                        f"thử lại {attempt}/{retries} sau {retry_wait:.0f}s...",
                        flush=True,
                    )
                    time.sleep(retry_wait)
                    continue
                raise XiaoyangApiError(f"{method} {path} — lỗi mạng: {e}") from e

            if r.status_code in (401, 403):
                raise XiaoyangAuthError(r.text[:300] or "Unauthorized")

            if r.status_code in retryable and attempt < retries:
                print(
                    f"  [XiaoYang] HTTP {r.status_code} (gateway timeout?) — "
                    f"thử lại {attempt}/{retries} sau {retry_wait:.0f}s...",
                    flush=True,
                )
                time.sleep(retry_wait)
                continue

            try:
                data = r.json() if r.content else {}
            except Exception:
                data = {"detail": (r.text or "")[:500]}

            if not r.ok:
                detail = data.get("detail") if isinstance(data, dict) else None
                snippet = detail or (r.text or "")[:300]
                if r.status_code in retryable:
                    raise XiaoyangApiError(
                        f"HTTP {r.status_code}: {snippet}\n"
                        "XiaoYang/CDN tạm quá tải (504 Hết thời gian cổng). "
                        "Thử lại sau vài phút hoặc tăng XIAOYANG_API_RETRIES."
                    )
                raise XiaoyangApiError(f"HTTP {r.status_code}: {snippet}")
            return data if isinstance(data, dict) else {"data": data}

        raise XiaoyangApiError(f"{method} {path} thất bại sau {retries} lần") from last_err

    def me(self) -> dict:
        """GET /api/v1/me — credit, email, ..."""
        return self._request("GET", "/api/v1/me")

    def modals(self) -> dict:
        """GET /api/v1/modals — model + option + giá credit."""
        return self._request("GET", "/api/v1/modals")

    def create_task(
        self,
        modal_key: str,
        option_key: str,
        prompt: str,
        *,
        image_url: str | None = None,
        video_url: str | None = None,
        clothes_image_url: str | None = None,
        motion_orientation: str | None = None,
        wardrobe_replace: str | None = None,
        ratio: str | None = None,
        enhance_4k: bool | None = None,
    ) -> dict:
        """POST /api/v1/tasks — trả task_id, status, credits."""
        modal_key = (modal_key or "").strip()
        if modal_key.startswith("motion_"):
            if not image_url or not video_url:
                raise ValueError("Motion Control cần image_url và video_url")
            motion_orientation = (motion_orientation or "video").strip()
            if is_workers_query_url(image_url) or is_workers_query_url(video_url):
                from xiaoyang_direct import resolve_api_v1_media_urls

                image_url, video_url = resolve_api_v1_media_urls(image_url, video_url)
            image_url, video_url = validate_motion_media(image_url, video_url, for_api_v1=True)
        else:
            if image_url:
                image_url = normalize_public_media_url(image_url)
            if video_url:
                video_url = normalize_public_media_url(video_url)
            if clothes_image_url:
                clothes_image_url = normalize_public_media_url(clothes_image_url)

        body = {
            "modal_key": modal_key,
            "option_key": option_key,
            "prompt": prompt,
        }
        if image_url:
            body["image_url"] = image_url
        if video_url:
            body["video_url"] = video_url
        if clothes_image_url:
            body["clothes_image_url"] = clothes_image_url
        if motion_orientation:
            body["motion_orientation"] = motion_orientation
        if wardrobe_replace:
            body["wardrobe_replace"] = wardrobe_replace
        if ratio:
            body["ratio"] = ratio
        if enhance_4k is not None:
            body["enhance_4k"] = enhance_4k
        return self._request(
            "POST",
            "/api/v1/tasks",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=int(os.environ.get("XIAOYANG_CREATE_TIMEOUT_SEC", "120")),
        )

    def get_task(self, task_id: str) -> dict:
        """GET /api/v1/tasks/{task_id} — poll QUEUED/PENDING/PROCESSING/SUCCESS/FAIL."""
        return self._request("GET", f"/api/v1/tasks/{task_id}")

    def download_task(self, task_id: str, dest_path: str) -> str:
        """GET /api/v1/tasks/{task_id}/download — lưu file kết quả."""
        dest_path = os.path.abspath(dest_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with self.session.get(
            self._url(f"/api/v1/tasks/{task_id}/download"),
            stream=True,
            timeout=int(os.environ.get("XIAOYANG_DOWNLOAD_TIMEOUT_SEC", "600")),
        ) as r:
            if r.status_code in (401, 403):
                raise XiaoyangAuthError(r.text[:300] or "Unauthorized")
            if not r.ok:
                raise XiaoyangApiError(f"Download HTTP {r.status_code}: {(r.text or '')[:300]}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest_path

    def try_delete_task(self, task_id: str) -> bool:
        """Xóa task trên XiaoYang sau khi đã trả hàng (endpoint có thể chưa mở — bỏ qua lỗi)."""
        try:
            self._request("DELETE", f"/api/v1/tasks/{task_id}", timeout=30)
            return True
        except XiaoyangApiError as e:
            print(f"⚠️ XiaoYang delete task {task_id}: {e}")
            return False
