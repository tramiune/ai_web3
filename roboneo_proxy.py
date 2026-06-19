"""VNsProxy + RoboNeo login helper."""

from __future__ import annotations

import os
from typing import Any

import requests

VNS_BASE = "https://vnsproxy.com/api/client"
MEITU_OAUTH = "https://account.meitu.com/oauth/access_token"
MEITU_TOKEN_INFO = "https://api.account.meitu.com/oauth/get_token_info"
ROBONEO_CLIENT_ID = "1189857647"
ROBONEO_WEB_VERSION = "4.9.0"
ROBONEO_ZIP_VERSION = "4.76000"
# RoboneoMulti dùng secret này (khác secret web thường)
ROBONEO_CLIENT_SECRET = os.getenv(
    "ROBONEO_CLIENT_SECRET", "45C30555F10E49629098A75F95828DA6"
)


def proxy_dict_from_key(
    proxy_key: str,
    *,
    rotate: bool = False,
    province_id: int | None = None,
) -> tuple[dict[str, str], str]:
    """Lấy IP từ VNsProxy key → (proxies requests, host:port)."""
    params: dict[str, str | int] = {"proxy_key": proxy_key}
    if province_id is not None:
        params["province_id"] = province_id

    host = ""
    if not rotate:
        r = requests.get(
            f"{VNS_BASE}/proxy/current",
            params={"proxy_key": proxy_key},
            timeout=30,
        )
        r.raise_for_status()
        host = (r.json().get("proxy") or "").strip()

    if rotate:
        requests.post(
            f"{VNS_BASE}/proxy/remove",
            params={"proxy_key": proxy_key},
            timeout=30,
        ).raise_for_status()
        host = ""

    if not host:
        r = requests.get(
            f"{VNS_BASE}/proxy/available",
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        host = (data.get("proxy") or "").strip()
        if not host:
            raise RuntimeError(f"Không lấy được IP cho key {proxy_key}: {data}")

    url = f"http://{host}"
    return {"http": url, "https": url}, host


def proxy_dict_rotate_with_fallback(
    proxy_key: str,
    *,
    province_id: int | None = None,
) -> tuple[dict[str, str], str, bool]:
    """Xoay IP mới; nếu 429 → dùng IP hiện tại (nếu còn). Trả (proxies, host, rotated)."""
    current_proxies: dict[str, str] | None = None
    current_host = ""
    try:
        current_proxies, current_host = proxy_dict_from_key(
            proxy_key, rotate=False, province_id=province_id
        )
    except Exception:
        pass

    try:
        proxies, host = proxy_dict_from_key(proxy_key, rotate=True, province_id=province_id)
        return proxies, host, True
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429 and current_host:
            print(f"⚠ VNsProxy 429 — dùng IP hiện tại {current_host}")
            return current_proxies or {}, current_host, False
        raise
    except Exception as exc:
        if "429" in str(exc) and current_host:
            print(f"⚠ VNsProxy 429 — dùng IP hiện tại {current_host}")
            return current_proxies or {}, current_host, False
        raise


def probe_proxy(proxies: dict[str, str] | None, *, timeout: float = 15) -> bool:
    """True nếu proxy kết nối được (bất kỳ HTTP response nào từ Meitu)."""
    if not proxies:
        return True
    try:
        requests.get(
            "https://account.meitu.com/",
            proxies=proxies,
            timeout=timeout,
            allow_redirects=True,
        )
        return True
    except (
        requests.exceptions.ProxyError,
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ConnectionError,
    ):
        return False


def roboneo_login(
    email: str,
    password: str,
    *,
    proxy_key: str | None = None,
    proxies: dict[str, str] | None = None,
    mt_g: str | None = None,
) -> dict[str, Any]:
    """Login Meitu/RoboNeo (grant_type=email). Trả response OAuth."""
    if proxy_key and not proxies:
        proxies, _ = proxy_dict_from_key(proxy_key)
    s = requests.Session()
    if proxies:
        s.proxies.update(proxies)
    login_data: dict[str, Any] = {
        "client_id": ROBONEO_CLIENT_ID,
        "client_secret": ROBONEO_CLIENT_SECRET,
        "grant_type": "email",
        "username": email,
        "password": password,
        "email": email,
        "client_language": "en",
        "country_code": os.getenv("ROBONEO_COUNTRY_CODE", "VN"),
        "is_web": "1",
        "client_accept_cookies": "1",
        "overseas": "1",
        "client_type": "2",
        "web_version": ROBONEO_WEB_VERSION,
        "zip_version": ROBONEO_ZIP_VERSION,
    }
    if mt_g:
        login_data["mt_g"] = mt_g
    r = s.post(MEITU_OAUTH, data=login_data, timeout=30)
    payload = r.json()
    code = (payload.get("meta") or {}).get("code")
    if code != 0:
        msg = (payload.get("meta") or {}).get("msg") or payload
        raise RuntimeError(f"Login fail (code {code}): {msg}")
    return payload["response"]
