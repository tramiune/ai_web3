"""Chuẩn bị URL *direct* cho API v1 XiaoYang (chỉ cần XIAOYANG_API_KEY).

XiaoYang server tải image_url/video_url từ phía họ. Link Workers ?file=... thường
bị FAIL (E_DIRECT_MEDIA_URL). Web không cần vì upload lên XiaoYang → token nội bộ.

Giải pháp bot không cookie:
  1) URL đã là file trực tiếp (.png/.mp4), hoặc
  2) Worker riêng xiaoyang-direct-worker (XIAOYANG_DIRECT_WORKER_URL), hoặc
  3) Mirror lên R2 public (R2_* trong .env).
"""

from __future__ import annotations

import os
import re
import time
from urllib.parse import quote, urlparse

import requests

from xiaoyang_media import WORKER_HOST, is_workers_query_url, normalize_public_media_url

_DIRECT_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")


class DirectMediaError(RuntimeError):
    pass


def direct_worker_base() -> str:
    from project_env import get_env

    return get_env("XIAOYANG_DIRECT_WORKER_URL").rstrip("/")


def is_direct_media_url(url: str) -> bool:
    """URL mà server XiaoYang có thể GET thẳng file (path có đuôi ảnh/video)."""
    u = urlparse((url or "").strip())
    if not u.scheme.startswith("http"):
        return False
    if is_workers_query_url(url):
        return False
    path = (u.path or "").lower()
    return any(path.endswith(ext) for ext in _DIRECT_EXT)


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    url = normalize_public_media_url(url)
    r = requests.get(
        url,
        timeout=int(os.environ.get("XIAOYANG_FETCH_TIMEOUT_SEC", "300")),
        headers={"User-Agent": os.environ.get("XIAOYANG_USER_AGENT", "Mozilla/5.0")},
    )
    r.raise_for_status()
    ctype = (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
    return r.content, ctype


def _guess_filename(url: str, default: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] if path else ""
    if name and "." in name:
        return re.sub(r"[^\w.\-]+", "_", name)
    return default


def upload_file_to_r2_public(file_path: str, key: str, content_type: str) -> str:
    """Upload file lên R2 public bucket (multipart, không giới hạn 100MB Worker)."""
    try:
        import boto3
    except ImportError as e:
        raise DirectMediaError("Cần boto3 để upload direct R2: pip install boto3") from e

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.environ.get("R2_BUCKET_NAME", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE", "").strip().rstrip("/")

    missing = [n for n, v in [
        ("R2_ACCOUNT_ID", account),
        ("R2_ACCESS_KEY_ID", access),
        ("R2_SECRET_ACCESS_KEY", secret),
        ("R2_BUCKET_NAME", bucket),
        ("R2_PUBLIC_BASE", public_base),
    ] if not v]
    if missing:
        raise DirectMediaError("Thiếu biến .env R2 direct: " + ", ".join(missing))

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
    )
    key = key.lstrip("/")
    # Token R2 thường chỉ có Object Write — multipart bị AccessDenied; dùng single PUT (≤5GB).
    with open(file_path, "rb") as f:
        client.put_object(Bucket=bucket, Key=key, Body=f, ContentType=content_type)
    # pub-*.r2.dev không serve prefix results/ — dùng Worker (cùng bucket MY_R2_BUCKET).
    from xiaoyang_media import WORKER_BASE

    return f"{WORKER_BASE}/?file={quote(key)}"


def upload_bytes_to_r2_public(data: bytes, key: str, content_type: str) -> str:
    """PUT lên bucket R2 public → URL https://pub-xxx.r2.dev/key"""
    try:
        import boto3
    except ImportError as e:
        raise DirectMediaError(
            "Cần boto3 để mirror lên R2: pip install boto3"
        ) from e

    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.environ.get("R2_BUCKET_NAME", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE", "").strip().rstrip("/")

    missing = [n for n, v in [
        ("R2_ACCOUNT_ID", account),
        ("R2_ACCESS_KEY_ID", access),
        ("R2_SECRET_ACCESS_KEY", secret),
        ("R2_BUCKET_NAME", bucket),
        ("R2_PUBLIC_BASE", public_base),
    ] if not v]
    if missing:
        raise DirectMediaError(
            "Thiếu biến .env để mirror Workers → R2: " + ", ".join(missing)
        )

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
    )
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return f"{public_base}/{key.lstrip('/')}"


def upload_bytes_to_direct_worker(
    data: bytes,
    folder: str,
    filename: str,
    content_type: str,
) -> str:
    """POST lên worker xiaoyang-direct-media → directUrl path /characters/...png"""
    base = direct_worker_base()
    if not base:
        raise DirectMediaError("Thiếu XIAOYANG_DIRECT_WORKER_URL trong .env")
    if folder not in ("characters", "motions"):
        raise DirectMediaError(f"folder không hợp lệ: {folder}")

    post_url = f"{base}/upload/{folder}?name={quote(filename)}"
    r = requests.post(
        post_url,
        data=data,
        headers={"Content-Type": content_type},
        timeout=int(os.environ.get("XIAOYANG_UPLOAD_TIMEOUT_SEC", "300")),
    )
    if not r.ok:
        raise DirectMediaError(f"Direct worker upload HTTP {r.status_code}: {(r.text or '')[:300]}")
    body = r.json() if r.content else {}
    direct = (body.get("directUrl") or body.get("url") or "").strip()
    if not direct:
        raise DirectMediaError(f"Direct worker không trả directUrl: {r.text[:200]}")
    return direct


def mirror_url_to_direct(url: str, *, folder: str) -> str:
    """Workers ?file= → direct worker (ưu tiên) hoặc R2 public."""
    if is_direct_media_url(url):
        return url.strip()
    if not is_workers_query_url(url) and WORKER_HOST not in (urlparse(url).hostname or "").lower():
        raise DirectMediaError(
            f"URL không phải Workers và cũng không phải link file trực tiếp: {url[:120]}"
        )
    data, ctype = _fetch_bytes(url)
    cl = ctype.lower()
    if "jpeg" in cl or "jpg" in cl or data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif "png" in cl or data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif "webp" in cl:
        ext = ".webp"
    elif "video" in cl or (len(data) >= 8 and data[4:8] == b"ftyp"):
        ext = ".mp4"
    else:
        ext = ".bin"
    fname = _guess_filename(url, f"media{ext}")

    if direct_worker_base():
        return upload_bytes_to_direct_worker(data, folder, fname, ctype)

    prefix = os.environ.get("R2_KEY_PREFIX", "xiaoyang").strip().strip("/")
    key = f"{prefix}/{folder}/{int(time.time() * 1000)}_{fname}"
    return upload_bytes_to_r2_public(data, key, ctype)


def resolve_api_v1_media_urls(image_url: str, video_url: str) -> tuple[str, str]:
    """
    Trả (image_url, video_url) dùng được với POST /api/v1/tasks (chỉ Bearer API key).
    """
    image_url = (image_url or "").strip()
    video_url = (video_url or "").strip()
    if not image_url or not video_url:
        raise DirectMediaError("Thiếu image_url hoặc video_url")

    if is_direct_media_url(image_url) and is_direct_media_url(video_url):
        return image_url, video_url

    if is_workers_query_url(image_url) or is_workers_query_url(video_url):
        from project_env import get_env

        if not direct_worker_base() and not get_env("R2_PUBLIC_BASE"):
            raise DirectMediaError(
                "Link MotionAI Workers (?file=) không dùng trực tiếp với API v1.\n"
                "Chọn một:\n"
                "  A) Deploy xiaoyang-direct-worker + XIAOYANG_DIRECT_WORKER_URL (khuyến nghị).\n"
                "  B) R2_* + R2_PUBLIC_BASE — bot mirror qua boto3.\n"
                "  C) URL direct sẵn trong .env (pub-xxx.r2.dev/.../file.mp4).\n"
                "  D) Luồng web + XIAOYANG_COOKIE (xy_motion_run.py)."
            )
        dest = "direct worker" if direct_worker_base() else "R2 public"
        print(f"Mirror Workers → {dest} (API-only, không cookie)...")
        image_url = mirror_url_to_direct(image_url, folder="characters")
        video_url = mirror_url_to_direct(video_url, folder="motions")
        print(f"  image: {image_url}")
        print(f"  video: {video_url}")

    if not is_direct_media_url(image_url) or not is_direct_media_url(video_url):
        raise DirectMediaError("Sau mirror vẫn không có URL direct — kiểm tra R2_PUBLIC_BASE")

    return image_url, video_url


def _worker_upload_max_bytes() -> int:
    from project_env import get_env

    return int(get_env("R2_WORKER_MAX_BYTES", str(90 * 1024 * 1024)))


def r2_direct_configured() -> bool:
    keys = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "R2_PUBLIC_BASE")
    return all(os.environ.get(k, "").strip() for k in keys)


def worker_result_download_url(object_key: str) -> str:
    from xiaoyang_media import WORKER_BASE

    return f"{WORKER_BASE}/?file={quote(object_key.lstrip('/'))}"


def _url_is_downloadable(url: str, *, timeout: int = 30) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code == 200:
            return True
        if r.status_code == 405:
            r = requests.get(
                url,
                stream=True,
                timeout=timeout,
                headers={"Range": "bytes=0-0"},
            )
            return r.status_code in (200, 206)
    except Exception:
        pass
    return False


def _resolve_public_result_url(object_key: str, pub_url: str | None = None) -> str:
    """Chỉ trả Worker ?file= — pub-xxx.r2.dev hay 404 dù boto3 upload R2 OK."""
    del pub_url  # không dùng làm link khách
    worker_url = worker_result_download_url(object_key)
    for wait_sec, timeout in ((0, 30), (2, 60), (4, 90)):
        if wait_sec:
            time.sleep(wait_sec)
        if _url_is_downloadable(worker_url, timeout=timeout):
            print(f"✅ Link tải khách (Worker): {worker_url[:100]}...")
            return worker_url
    raise DirectMediaError(
        f"Upload xong nhưng Worker chưa phục vụ được file. key={object_key.lstrip('/')}"
    )


def _upload_via_motion_worker(file_path: str, object_key: str, content_type: str) -> str | None:
    from xiaoyang_media import WORKER_BASE

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"📤 Upload Worker ({size_mb:.1f} MB)...")
    url = (
        f"{WORKER_BASE}/?file={quote(object_key)}"
        f"&t={int(time.time() * 1000)}"
    )
    timeout = int(os.environ.get("R2_WORKER_UPLOAD_TIMEOUT_SEC", "600"))
    with open(file_path, "rb") as f:
        response = requests.post(url, data=f, headers={"Content-Type": content_type}, timeout=timeout)
    if response.status_code == 200:
        try:
            return _resolve_public_result_url(object_key)
        except DirectMediaError as e:
            print(f"❌ {e}")
            return None
    if response.status_code == 413:
        print("⚠️ Worker 413 Payload Too Large (>~100MB Cloudflare)")
        return None
    print(f"❌ Worker upload HTTP {response.status_code}: {(response.text or '')[:200]}")
    return None


def upload_result_file(file_path: str, folder: str = "results", content_type: str = "video/mp4") -> str:
    """
    Upload video kết quả; trả URL khách tải được (Worker ?file=, verify HEAD).
    File ≤ R2_WORKER_MAX_BYTES: Worker. File lớn hoặc 413 → upload direct R2 (boto3).
    """
    if not os.path.isfile(file_path):
        raise DirectMediaError(f"Không tìm thấy file upload: {file_path}")

    max_worker = _worker_upload_max_bytes()
    size = os.path.getsize(file_path)
    object_key = f"{folder}/{int(time.time() * 1000)}_{os.path.basename(file_path)}"

    if size <= max_worker:
        url = _upload_via_motion_worker(file_path, object_key, content_type)
        if url:
            return url
    else:
        print(
            f"⚠️ File {size / (1024 * 1024):.1f} MB > "
            f"{max_worker / (1024 * 1024):.0f} MB — chuyển upload direct R2"
        )

    if r2_direct_configured():
        print(f"📤 Upload direct R2 ({size / (1024 * 1024):.1f} MB)...")
        pub_url = upload_file_to_r2_public(file_path, object_key, content_type)
        return _resolve_public_result_url(object_key, pub_url)

    raise DirectMediaError(
        "Worker từ chối file lớn (>~100MB) — cần cấu hình R2_* trong .env để upload direct."
    )
