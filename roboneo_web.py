"""
RoboNeo (Meitu) web client — clone API flow từ RoboneoMulti.

Login OAuth (grant_type=email) → gateway sync (initconfig, createroom, …)
→ upload S3 → canvas workflow → nodeexecute → poll → tải MP4.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import random
import re
import string
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from project_env import get_env, load_project_env
from roboneo_proxy import (
    MEITU_TOKEN_INFO,
    ROBONEO_CLIENT_ID,
    ROBONEO_CLIENT_SECRET,
    ROBONEO_WEB_VERSION,
    ROBONEO_ZIP_VERSION,
    probe_proxy,
    proxy_dict_from_key,
    roboneo_login,
)

load_project_env()

GATEWAY_BASE = "https://ai-engine-gateway-roboneo.meitu.com/roboneo/sync/request"
WEBAPI_BASE = "https://webapi.roboneo.com"
STRATEGY_POLICY_URL = "https://strategy.app.meitudata.com/upload/policy"
ORIGIN = "https://www.roboneo.com"
WEB_VERSION = ROBONEO_WEB_VERSION
ZIP_VERSION = ROBONEO_ZIP_VERSION
def generate_node_id(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


MOTION_MCP_CATEGORY_ID = "93"
MOTION_TOOL_ABSTRACT = "01KSVA4KGZMHTN4FVWNFK66VH1_.tt.1"
MOTION_API_V26 = "video_bonbon_motioncontrol_v26"
MOTION_API_V30 = "video_bonbon_motioncontrol_v30"
MOTION_APIS = {
    "v26": MOTION_API_V26,
    "kling26": MOTION_API_V26,
    "kling-2.6": MOTION_API_V26,
    "v30": MOTION_API_V30,
    "kling30": MOTION_API_V30,
    "kling-3.0": MOTION_API_V30,
}


def resolve_motion_api(model: str | None) -> str:
    key = (model or get_env("ROBONEO_MOTION_MODEL", "v26") or "v26").strip().lower()
    api = MOTION_APIS.get(key)
    if not api:
        allowed = ", ".join(sorted(MOTION_APIS))
        raise RoboNeoError(f"model không hợp lệ: {model!r} (RoboNeo motion: {allowed})")
    return api


SURFACE_TEAM_STUDIO = "team_studio"
SURFACE_AI_FLOW = "ai_flow"
SURFACE_ALIASES = {
    "team_studio": SURFACE_TEAM_STUDIO,
    "studio": SURFACE_TEAM_STUDIO,
    "team": SURFACE_TEAM_STUDIO,
    "ai_flow": SURFACE_AI_FLOW,
    "flow": SURFACE_AI_FLOW,
}


def resolve_surface(surface: str | None) -> str:
    key = (
        surface or get_env("ROBONEO_SURFACE", SURFACE_TEAM_STUDIO) or SURFACE_TEAM_STUDIO
    ).strip().lower()
    resolved = SURFACE_ALIASES.get(key)
    if not resolved:
        allowed = ", ".join(sorted(SURFACE_ALIASES))
        raise RoboNeoError(f"surface không hợp lệ: {surface!r} (dùng: {allowed})")
    return resolved


def surface_config(surface: str) -> dict[str, Any]:
    if surface == SURFACE_TEAM_STUDIO:
        return {
            "position_type": "/team_studio",
            "room_type": 5,
            "workflow_version": "v2",
            "page_path": "/team_studio",
            "use_canvas": False,
        }
    return {
        "position_type": "/ai_flow",
        "room_type": 2,
        "workflow_version": None,
        "page_path": "/ai_flow",
        "use_canvas": True,
    }


MOTION_MODE_ALIASES = {
    "std": "normal",
    "standard": "normal",
    "normal": "normal",
    "pro": "high",
    "advanced": "high",
    "high": "high",
}
def session_file_for_account(account_id: str = "default") -> Path:
    custom = (get_env("ROBONEO_SESSION_FILE") or "").strip()
    if custom and account_id in ("default", ""):
        return Path(__file__).resolve().parent / custom
    safe = re.sub(r"[^a-z0-9_-]", "_", (account_id or "default").lower())
    return Path(__file__).resolve().parent / f"roboneo_session_{safe}.json"


def resolve_motion_mode(mode: str | None) -> str:
    """Map UI std/pro → API model_pattern.type (normal | high)."""
    key = (mode or get_env("ROBONEO_MOTION_MODE", "std") or "std").strip().lower()
    pattern = MOTION_MODE_ALIASES.get(key)
    if not pattern:
        allowed = ", ".join(sorted(MOTION_MODE_ALIASES))
        raise RoboNeoError(f"mode không hợp lệ: {mode!r} (dùng: {allowed})")
    return pattern


def model_pattern_payload(pattern_type: str) -> dict[str, str]:
    return {"type": pattern_type}


class RoboNeoError(RuntimeError):
    pass


class RoboNeoAuthError(RoboNeoError):
    pass


class RoboNeoGatewayError(RoboNeoError):
    def __init__(self, error_code: int, error_msg: str, payload: dict | None = None):
        self.error_code = error_code
        self.error_msg = error_msg
        self.payload = payload or {}
        super().__init__(f"gateway error {error_code}: {error_msg}")


def generate_gid() -> str:
    """Format gid giống RoboneoMulti (hex segments + digits)."""
    alphabet = "0123456789abcdef"

    def hex_seg(n: int) -> str:
        return "".join(random.choice(alphabet) for _ in range(n))

    def digit_seg(n: int) -> str:
        return "".join(str(random.randint(0, 9)) for _ in range(n))

    return f"{hex_seg(15)}-{hex_seg(15)}-{digit_seg(8)}-{digit_seg(7)}-{hex_seg(15)}"


def generate_trace_id() -> str:
    return str(uuid.uuid4())


def _proxy_host_from_url(proxy_url: str) -> str | None:
    raw = (proxy_url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        return raw
    parsed = urlparse(raw)
    if parsed.hostname and parsed.port:
        return f"{parsed.hostname}:{parsed.port}"
    return None


def generate_timestamp_rand() -> str:
    ms = int(time.time() * 1000)
    rand = random.randint(0, 99_999_999)
    return f"{ms}-{rand:08d}"


def _media_entry(path: Path, access_url: str) -> dict[str, Any]:
    suffix = path.suffix.lstrip(".").lower() or "bin"
    uri = access_url.split("?")[0].rstrip("/").split("/")[-1]
    entry: dict[str, Any] = {
        "name": path.stem,
        "originUrl": access_url,
        "suffix": suffix,
        "uri": uri,
        "url": access_url,
    }
    if suffix in {"mp4", "mov", "webm", "avi"}:
        sep = "&" if "?" in access_url else "?"
        entry["coverUrl"] = f"{access_url}{sep}vframe/jpg/offset/0"
        entry["type"] = "video"
    return entry


def _aws4_signature(credentials: dict[str, Any], region: str, date_ymd: str, string_to_sign: str) -> str:
    secret = credentials["secret_key"].encode("utf-8")
    k_date = hmac.new(b"AWS4" + secret, date_ymd.encode("utf-8"), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def _oss_post_signature(
    credentials: dict[str, Any],
    region: str,
    date_ymd: str,
    policy_base64: str,
    *,
    service: str = "s3",
) -> str:
    """Aliyun OSS POST policy signature (RoboneoMulti create_signature)."""
    secret = credentials["secret_key"].encode("utf-8")
    k_date = hmac.new(b"AWS4" + secret, date_ymd.encode("utf-8"), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return hmac.new(k_signing, policy_base64.encode("utf-8"), hashlib.sha256).hexdigest()


class RoboNeoWebClient:
    """Gọi API RoboNeo trực tiếp (giống RoboneoMulti)."""

    def __init__(self, account_id: str = "default", session: requests.Session | None = None):
        load_project_env()
        self.account_id = account_id or "default"
        self.session_file = session_file_for_account(self.account_id)
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": get_env(
                    "ROBONEO_USER_AGENT",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/",
            }
        )
        self._state: dict[str, Any] = {}
        self._gid: str | None = None
        self._load_session()

    @property
    def access_token(self) -> str:
        tok = self._state.get("access_token") or ""
        if not tok:
            raise RoboNeoAuthError("Chưa có access_token — chạy login trước")
        return tok

    @property
    def uid(self) -> int:
        uid = self._state.get("uid")
        if uid is None:
            raise RoboNeoAuthError("Chưa có uid — chạy login trước")
        return int(uid)

    @property
    def gid(self) -> str:
        if not self._gid:
            self._gid = self._state.get("gid") or generate_gid()
        return self._gid

    def _save_session(self) -> None:
        data = dict(self._state)
        if self._state.get("proxy"):
            data["proxy"] = self._state["proxy"]
        if self._gid:
            data["gid"] = self._gid
        self.session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_session(self) -> None:
        if not self.session_file.is_file():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except Exception:
            return
        if not data.get("access_token"):
            return
        self._state = data
        self._gid = data.get("gid")
        proxy_host = (data.get("proxy") or "").strip()
        if proxy_host:
            url = f"http://{proxy_host}"
            self.session.proxies.update({"http": url, "https": url})

    def _proxy_key(self) -> str | None:
        key = (get_env("ROBONEO_PROXY_KEY") or "").strip()
        return key or None

    def _apply_proxies(self, host: str | None) -> None:
        if host:
            url = f"http://{host}"
            self.session.proxies.update({"http": url, "https": url})
            self._state["proxy"] = host
        else:
            self.session.proxies.clear()
            self._state.pop("proxy", None)

    def _relogin_if_possible(self, reason: str) -> None:
        email = get_env("ROBONEO_EMAIL")
        password = get_env("ROBONEO_PASSWORD")
        if not email or not password:
            raise RoboNeoAuthError(
                f"{reason} — thiếu credential trong .env, chạy: python3 roboneo_motion_bot.py login"
            )
        print(f"↻ {reason} → đang login lại…")
        resp = roboneo_login(email, password, proxies=dict(self.session.proxies) or None)
        self._state.update(
            {
                "access_token": resp["access_token"],
                "refresh_token": resp.get("refresh_token", ""),
                "uid": resp.get("uid") or (resp.get("user") or {}).get("id"),
                "webview_token": resp.get("webview_token", ""),
                "redirect_token_code": resp.get("redirect_token_code", ""),
                "login_proxy": self._state.get("proxy"),
            }
        )
        if not self._gid:
            self._gid = generate_gid()
        self._save_session()

    def sync_proxy(self, *, recover: bool = True, relogin_on_change: bool = True) -> str:
        """
        Đồng bộ IP từ VNsProxy (bỏ IP chết trong session cũ).
        recover=True: rotate IP mới nếu current chết.
        """
        if (
            self._state.get("session_source") == "roboneo_multi"
            and get_env("ROBONEO_FORCE_PROXY", "0") != "1"
        ):
            return self._state.get("proxy") or "direct"

        key = self._proxy_key()
        if not key:
            self._apply_proxies(None)
            self._save_session()
            return "direct"

        old_host = self._state.get("proxy") or self._state.get("login_proxy")
        proxies, host = proxy_dict_from_key(key, rotate=False)
        if probe_proxy(proxies):
            if host != old_host:
                print(f"↻ Proxy sync: {old_host or '?'} → {host}")
            self._apply_proxies(host)
            self._save_session()
            if relogin_on_change and old_host and host != old_host and self._state.get("access_token"):
                self._relogin_if_possible(f"IP đổi ({old_host} → {host})")
            return host

        if not recover:
            raise RoboNeoError(
                f"Proxy {host} chết. Chạy: python3 roboneo_motion_bot.py sync-proxy"
            )

        print(f"⚠️ Proxy {host} chết — đang lấy IP mới từ VNsProxy…")
        proxies, host = proxy_dict_from_key(key, rotate=True)
        if probe_proxy(proxies):
            self._apply_proxies(host)
            self._save_session()
            if self._state.get("access_token"):
                self._relogin_if_possible(f"IP mới {host}")
            else:
                print(f"✓ IP mới: {host} — chạy login")
            return host

        if get_env("ROBONEO_ALLOW_DIRECT", "1") == "1":
            print("⚠️ Proxy VNsProxy không dùng được — chuyển direct (IP máy bạn)")
            self._apply_proxies(None)
            self._save_session()
            if self._state.get("access_token"):
                self._relogin_if_possible("chạy direct không proxy")
            return "direct"

        raise RoboNeoError(
            "Proxy VNsProxy không kết nối được. Đổi key hoặc set ROBONEO_ALLOW_DIRECT=1 trong .env"
        )

    def doctor(self) -> dict[str, Any]:
        """Kiểm tra nhanh session + proxy + gateway."""
        report: dict[str, Any] = {
            "session_file": str(self.session_file),
            "has_token": bool(self._state.get("access_token")),
            "uid": self._state.get("uid"),
            "proxy_session": self._state.get("proxy"),
            "login_proxy": self._state.get("login_proxy"),
        }
        key = self._proxy_key()
        report["proxy_key"] = key or "(none)"
        if key:
            try:
                _, vns_host = proxy_dict_from_key(key, rotate=False)
                report["proxy_vns_current"] = vns_host
            except Exception as exc:
                report["proxy_vns_error"] = str(exc)
        mode = self.sync_proxy(recover=True, relogin_on_change=False)
        report["proxy_active"] = mode
        if self._state.get("access_token"):
            try:
                param = self.init_config()
                report["initconfig"] = "OK"
                report["initconfig_keys"] = list(param.keys())[:8]
            except RoboNeoGatewayError as exc:
                report["initconfig"] = f"error {exc.error_code}: {exc.error_msg}"
            try:
                meiye = self.meiye_query()
                report["meiyequery"] = {
                    "check_result": meiye.get("check_result"),
                    "amount": meiye.get("amount"),
                }
            except Exception as exc:
                report["meiyequery"] = f"error: {exc}"
        else:
            report["initconfig"] = "skipped (no token)"
        return report

    def _proxy_province_id(self) -> int | None:
        raw = (get_env("ROBONEO_PROXY_PROVINCE_ID") or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _apply_proxy_key(self, proxy_key: str, *, rotate: bool = False) -> str:
        province_id = self._proxy_province_id()
        proxies, host = proxy_dict_from_key(
            proxy_key, rotate=rotate, province_id=province_id
        )
        if not probe_proxy(proxies):
            if not rotate:
                proxies, host = proxy_dict_from_key(
                    proxy_key, rotate=True, province_id=province_id
                )
            if not probe_proxy(proxies):
                raise RoboNeoError(f"Không có proxy sống cho key {proxy_key}")
        self._apply_proxies(host)
        return host

    def login(
        self,
        email: str,
        password: str,
        *,
        proxy_key: str | None = None,
        rotate_proxy: bool = False,
    ) -> dict[str, Any]:
        """Login 1 lần, lưu session. Không gọi lại nếu token còn hạn."""
        key = proxy_key or self._proxy_key()
        if key:
            self._apply_proxy_key(key, rotate=rotate_proxy)
        else:
            self._apply_proxies(None)
        if not self._gid:
            self._gid = generate_gid()
        resp = roboneo_login(
            email,
            password,
            proxies=dict(self.session.proxies) or None,
            mt_g=self._gid,
        )
        self._state.update(
            {
                "access_token": resp["access_token"],
                "refresh_token": resp.get("refresh_token", ""),
                "uid": resp.get("uid") or (resp.get("user") or {}).get("id"),
                "webview_token": resp.get("webview_token", ""),
                "redirect_token_code": resp.get("redirect_token_code", ""),
                "login_proxy": self._state.get("proxy"),
                "gid": self._gid,
            }
        )
        try:
            self.fetch_token_info()
        except RoboNeoAuthError:
            pass
        self._save_session()
        return self._state

    def import_web_token(
        self,
        access_token: str,
        *,
        uid: int | None = None,
        refresh_token: str = "",
    ) -> dict[str, Any]:
        """Dùng access_token copy từ roboneo.com (DevTools → localStorage) sau login web."""
        token = access_token.strip()
        if not token:
            raise RoboNeoAuthError("Token trống")
        self._state["access_token"] = token
        if refresh_token:
            self._state["refresh_token"] = refresh_token
        if uid is not None:
            self._state["uid"] = uid
        elif not self._state.get("uid"):
            raise RoboNeoAuthError("Thiếu uid — thêm --uid từ localStorage")
        if not self._gid:
            self._gid = generate_gid()
        self._state["login_proxy"] = self._state.get("proxy")
        self._save_session()
        return self._state

    def import_from_multi_db(
        self,
        db_path: str | Path,
        *,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Import session từ RoboneoMulti SQLite (%USERPROFILE%\\.roboneo_multi\\database.db)."""
        import sqlite3

        path = Path(db_path)
        if not path.is_file():
            raise RoboNeoError(f"Không tìm thấy file: {path}")

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            if email:
                row = conn.execute(
                    "SELECT * FROM accounts WHERE email = ? COLLATE NOCASE",
                    (email,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM accounts
                    WHERE access_token IS NOT NULL AND TRIM(access_token) != ''
                    ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
        finally:
            conn.close()

        if not row:
            hint = f" email={email}" if email else ""
            raise RoboNeoError(f"Không có account trong database.db{hint}")

        token = (row["access_token"] or "").strip()
        if not token:
            raise RoboNeoError(f"Account {row['email']} chưa có access_token — login trên tool trước")

        try:
            uid = int(row["user_id"]) if row["user_id"] else None
        except (TypeError, ValueError):
            uid = None
        if uid is None:
            raise RoboNeoError(f"Account {row['email']} thiếu user_id trong database.db")

        self._state.update(
            {
                "access_token": token,
                "refresh_token": row["refresh_token"] or "",
                "uid": uid,
                "trace_id": row["trace_id"] or "",
                "room_id": row["room_id"] or "",
                "balance": row["balance"],
                "multi_email": row["email"],
                "session_source": "roboneo_multi",
            }
        )
        # mtg/sid: import từ DB cho nodeexecute; không gửi kèm initconfig (→ lỗi 95)
        if row["mtg"]:
            self._state["mtg"] = str(row["mtg"])
        if row["sid"]:
            self._state["sid"] = str(row["sid"])
        if row["gid"]:
            self._gid = str(row["gid"])
            self._state["gid"] = self._gid

        proxy_host = _proxy_host_from_url(row["http_proxy_url"] or "")
        if proxy_host:
            self._apply_proxies(proxy_host)
            self._state["login_proxy"] = proxy_host
        else:
            self._state.pop("proxy", None)
            self.session.proxies.clear()
            self._state["login_proxy"] = "direct"

        self._save_session()
        return self._state

    def ensure_session(
        self,
        email: str | None = None,
        password: str | None = None,
        *,
        proxy_key: str | None = None,
    ) -> None:
        self.sync_proxy(recover=True)
        if self._state.get("access_token"):
            return
        email = email or get_env("ROBONEO_EMAIL")
        password = password or get_env("ROBONEO_PASSWORD")
        if not email or not password:
            raise RoboNeoAuthError("Thiếu ROBONEO_EMAIL / ROBONEO_PASSWORD hoặc session file")
        self.login(email, password, proxy_key=proxy_key or self._proxy_key())

    def _gateway_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "origin": ORIGIN,
            "referer": f"{ORIGIN}/",
            "client-id": ROBONEO_CLIENT_ID,
            "access-token": self.access_token,
            "web-version": WEB_VERSION,
            "zip-version": ZIP_VERSION,
        }

    def _surface_tracking(self, surface: str, room_id: str = "") -> dict[str, Any]:
        cfg = surface_config(surface)
        page_path = cfg["page_path"]
        page_url = (
            f"{ORIGIN}{page_path}?room_id={room_id}"
            if room_id
            else f"{ORIGIN}{page_path}"
        )
        first_url = f"{ORIGIN}{page_path}" if surface == SURFACE_TEAM_STUDIO else f"{ORIGIN}/home"
        return {
            "tt_ttclid": "",
            "tt_tttp": (self._state.get("trace_id") or ""),
            "first_url": first_url,
            "page_url": page_url,
            "referrer": f"{ORIGIN}/project",
            "pixel_ready": 1,
        }

    def _ai_flow_tracking(self, room_id: str = "") -> dict[str, Any]:
        return self._surface_tracking(SURFACE_AI_FLOW, room_id)

    def _base_parameter(
        self,
        path_scene: str,
        *,
        position_type: str = "/home",
        **extra: Any,
    ) -> dict[str, Any]:
        trace_id = (self._state.get("trace_id") or "").strip() or generate_trace_id()
        param: dict[str, Any] = {
            "path_scene": path_scene,
            # RoboneoMulti: body.token = client_secret; header access-token = OAuth token
            "token": ROBONEO_CLIENT_SECRET,
            "gid": self.gid,
            "uid": str(self.uid),
            "trace_id": trace_id,
            "client_id": ROBONEO_CLIENT_ID,
            "app_scene": "roboneo",
            "area_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
            "lang": get_env("ROBONEO_LANG", "en"),
            "time_zone": get_env("ROBONEO_TIMEZONE", "Asia/Bangkok"),
            "extra": {
                "big_data_patch": {
                    "position_type": position_type,
                }
            },
        }
        if path_scene != "initconfig":
            for key in ("mtg", "sid"):
                val = (self._state.get(key) or "").strip()
                if val and path_scene not in {
                    "nodeexecute",
                    "nodeexecutequery",
                    "uploadpolicy",
                    "countcost",
                    "createroom",
                    "vipshow",
                    "meiyequery",
                }:
                    param[key] = val
        param.update(extra)
        return param

    def gateway(self, path_scene: str, **parameter: Any) -> dict[str, Any]:
        """POST gateway sync request (URL suffix = path_scene)."""
        body = {"parameter": self._base_parameter(path_scene, **parameter)}
        url = f"{GATEWAY_BASE}/{path_scene}"
        r = self.session.post(
            url,
            json=body,
            headers=self._gateway_headers(),
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        code = data.get("error_code", 0)
        if code != 0:
            raise RoboNeoGatewayError(
                int(code),
                str(data.get("error_msg") or ""),
                data,
            )
        return data.get("parameter") or data

    def webapi(self, path: str, *, method: str = "POST", params: dict | None = None, json_body: dict | None = None) -> dict[str, Any]:
        url = f"{WEBAPI_BASE}{path}"
        headers = self._gateway_headers()
        if method.upper() == "GET":
            r = self.session.get(url, params=params, headers=headers, timeout=60)
        else:
            r = self.session.post(url, params=params, json=json_body or {}, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        code = data.get("code", 0)
        if code not in (0, 200):
            raise RoboNeoError(f"webapi {path} code {code}: {data.get('message', data)}")
        return data.get("data") or data

    def init_config(self) -> dict[str, Any]:
        param = self.gateway("initconfig", send_num=1)
        for key in ("mtg", "sid", "gid", "trace_id"):
            val = param.get(key)
            if val:
                self._state[key] = val
                if key == "gid":
                    self._gid = str(val)
        self._save_session()
        return param

    def vip_show(self) -> dict[str, Any]:
        return self.gateway("vipshow", send_num=1)

    def meiye_query(self, *, room_id: str | None = None, surface: str | None = None) -> dict[str, Any]:
        """RoboneoMulti 1.0.8: kiểm tra credit trước khi chạy task (thay vipshow)."""
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        room_id = room_id or (self._state.get("room_id") or "")
        result = self.gateway(
            "meiyequery",
            position_type=cfg["position_type"],
            send_num=1,
            room_id=room_id,
            **self._surface_tracking(surface, room_id),
        )
        if result.get("amount") is not None:
            self._state["balance"] = result["amount"]
            self._save_session()
        return result

    def fetch_token_info(self) -> dict[str, Any]:
        """RoboneoMulti 1.0.8: refresh token + sid sau OAuth login."""
        refresh = (self._state.get("refresh_token") or "").strip()
        if not refresh:
            return {}
        params = {
            "client_id": ROBONEO_CLIENT_ID,
            "client_language": get_env("ROBONEO_LANG", "en"),
            "mt_g": self.gid,
            "overseas": "1",
            "client_type": "2",
            "web_version": WEB_VERSION,
            "zip_version": ZIP_VERSION,
            "is_web": "1",
            "client_accept_cookies": "1",
            "country_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
            "refresh_token": refresh,
        }
        r = self.session.get(
            MEITU_TOKEN_INFO,
            params=params,
            headers={"access-token": self.access_token},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        meta = data.get("meta") or {}
        if meta.get("code", 0) not in (0, None):
            raise RoboNeoAuthError(f"get_token_info: {meta.get('msg') or meta}")
        response = data.get("response") or {}
        if response.get("access_token"):
            self._state["access_token"] = response["access_token"]
        if response.get("refresh_token"):
            self._state["refresh_token"] = response["refresh_token"]
        if meta.get("sid"):
            self._state["sid"] = str(meta["sid"])
        self._save_session()
        return response

    def count_cost(
        self,
        api_name: str = MOTION_API_V26,
        *,
        room_id: str | None = None,
        model_pattern: str | None = None,
        surface: str | None = None,
    ) -> dict[str, Any]:
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        room_id = room_id or (self._state.get("room_id") or "")
        pattern_type = resolve_motion_mode(model_pattern) if model_pattern else None
        item: dict[str, Any] = {
            "api_name": api_name,
            "item_type": "tool",
            "tool_name": api_name,
        }
        if pattern_type:
            item["model_pattern"] = model_pattern_payload(pattern_type)
        extra: dict[str, Any] = {}
        if pattern_type:
            extra["model_pattern"] = model_pattern_payload(pattern_type)
        return self.gateway(
            "countcost",
            position_type=cfg["position_type"],
            room_id=room_id,
            items=[item],
            send_num=1,
            **self._surface_tracking(surface, room_id),
            **extra,
        )

    def create_room(self, *, surface: str | None = None) -> str:
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        page_path = cfg["page_path"]
        param = self.gateway(
            "createroom",
            position_type=cfg["position_type"],
            room_type=cfg["room_type"],
            first_url=f"{ORIGIN}{page_path}",
            page_url=f"{ORIGIN}{page_path}",
            referrer=f"{ORIGIN}/project",
            send_num=1,
            pixel_ready=1,
        )
        room_id = param.get("room_id") or param.get("roomId") or ""
        if not room_id:
            raise RoboNeoError(f"createroom không trả room_id: {param}")
        self._state["room_id"] = room_id
        self._save_session()
        if cfg["use_canvas"]:
            self.canvas_init(room_id)
            self.canvas_save(room_id, {"nodes": [], "edges": []})
        return room_id

    def request_upload_sig(self, suffix: str, *, count: int = 1, surface: str | None = None) -> dict[str, Any]:
        """Gateway uploadpolicy → trả sig/sigTime/sigVersion (giống RoboneoMulti)."""
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        suffix = suffix.lstrip(".")
        sig_time = str(int(time.time()))
        room_id = (self._state.get("room_id") or "").strip()
        tracking = self._surface_tracking(surface, room_id)
        return self.gateway(
            "uploadpolicy",
            position_type=cfg["position_type"],
            upload_version="2",
            app="RoboNeo",
            type="roboneo_private_web",
            count=count,
            suffix=suffix,
            sig="",
            sigTime=sig_time,
            sigVersion="1.3",
            version="2",
            **tracking,
        )

    def fetch_strategy_policy(
        self,
        sig: str,
        sig_time: str,
        sig_version: str,
        suffix: str,
        *,
        count: int = 1,
    ) -> dict[str, Any]:
        suffix = suffix.lstrip(".")
        params = {
            "app": "RoboNeo",
            "count": count,
            "sig": sig,
            "sigTime": sig_time,
            "sigVersion": sig_version,
            "suffix": suffix,
            "type": "roboneo_private_web",
            "version": "2",
        }
        r = self.session.get(STRATEGY_POLICY_URL, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            raise RoboNeoError(f"strategy policy rỗng: {data!r}")
        oss = data[0].get("oss") or {}
        if not oss.get("credentials") or not oss.get("key"):
            raise RoboNeoError(f"strategy policy thiếu oss: {data!r}")
        return oss

    def _s3_post_upload(self, oss: dict[str, Any], path: Path) -> None:
        credentials = oss["credentials"]
        region = oss.get("region") or "oss-cn-beijing"
        bucket = oss.get("bucket") or "mt-roboneo-private-release"
        key = oss["key"]
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        ctype_prefix = f"{content_type.split('/', 1)[0]}/"

        # RoboneoMulti: YYYYMMDD + x-amz-date dùng local time; expiration dùng UTC
        date_ymd = time.strftime("%Y%m%d")
        amz_date = time.strftime("%Y%m%dT%H%M%SZ")
        expiration = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z",
            time.gmtime(time.time() + 600),
        )
        credential = f"{credentials['access_key']}/{date_ymd}/{region}/s3/aws4_request"
        policy_doc = {
            "expiration": expiration,
            "conditions": [
                {"bucket": bucket},
                ["starts-with", "$key", ""],
                ["starts-with", "$Content-Type", ctype_prefix],
                {"success_action_status": "200"},
                {"X-Amz-Credential": credential},
                {"X-Amz-Algorithm": "AWS4-HMAC-SHA256"},
                {"X-Amz-Security-Token": credentials["session_token"]},
                {"X-Amz-Date": amz_date},
            ],
        }
        policy_str = json.dumps(policy_doc, separators=(",", ":"), ensure_ascii=False)
        policy_b64 = base64.b64encode(policy_str.encode("utf-8")).decode("ascii")
        signature = _oss_post_signature(credentials, region, date_ymd, policy_b64)
        form = {
            "key": key,
            "content-type": content_type,
            "success_action_status": "200",
            "x-amz-credential": credential,
            "x-amz-algorithm": "AWS4-HMAC-SHA256",
            "x-amz-security-token": credentials["session_token"],
            "x-amz-date": amz_date,
            "policy": policy_b64,
            "x-amz-signature": signature,
        }
        host = f"{bucket}.upload.meitudata.com"
        with path.open("rb") as handle:
            r = self.session.post(
                f"https://{host}/",
                data=form,
                files={"file": (path.name, handle, content_type)},
                timeout=300,
            )
        if r.status_code not in (200, 201, 204):
            raise RoboNeoError(f"Upload S3 HTTP {r.status_code}: {r.text[:300]}")

    def create_asset(self, path: Path, access_url: str) -> dict[str, Any]:
        suffix = path.suffix.lstrip(".").lower() or "bin"
        mime, _ = mimetypes.guess_type(path.name)
        is_video = suffix in {"mp4", "mov", "webm", "avi"} or (
            mime is not None and mime.startswith("video/")
        )
        body: dict[str, Any] = {
            "client_id": ROBONEO_CLIENT_ID,
            "client_language": get_env("ROBONEO_LANG", "en"),
            "country_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
            "gnum": self.gid,
            "material_type": "video" if is_video else "image",
            "name": path.stem,
            "task_type": "workflow",
            "url": access_url,
            "originUrl": access_url,
            "watermark_url": None,
        }
        if is_video:
            sep = "&" if "?" in access_url else "?"
            body["thumbnail_url"] = f"{access_url}{sep}vframe/jpg/offset/0"
        else:
            body["ext"] = suffix
            from PIL import Image

            with Image.open(path) as img:
                body["width"], body["height"] = img.size
        return self.webapi("/asset_library/asset/create.json", json_body=body)

    def upload_file(self, local_path: str | Path, *, surface: str | None = None) -> dict[str, Any]:
        path = Path(local_path)
        if not path.is_file():
            raise RoboNeoError(f"File không tồn tại: {path}")
        suffix = path.suffix.lstrip(".") or "bin"

        sig_wrap = self.request_upload_sig(suffix, surface=surface)
        sig = sig_wrap.get("sig") or ""
        sig_time = str(sig_wrap.get("sigTime") or int(time.time()))
        sig_version = str(sig_wrap.get("sigVersion") or "1.2")
        if not sig:
            raise RoboNeoError(f"uploadpolicy không trả sig: {sig_wrap}")

        oss = self.fetch_strategy_policy(sig, sig_time, sig_version, suffix)
        self._s3_post_upload(oss, path)
        access_url = oss.get("access_url") or oss.get("data") or ""
        if not access_url:
            key = oss.get("key", "")
            access_url = f"https://roboneo-private.meitudata.com/{key}"

        asset = self.create_asset(path, access_url)
        asset_id = asset.get("asset_id")
        if asset_id is None:
            raise RoboNeoError(f"create_asset không trả asset_id: {asset}")
        return {"url": access_url, "asset_id": int(asset_id)}

    def canvas_init(self, room_id: str) -> dict[str, Any]:
        init_body = {
            "gnum": self.gid,
            "client_id": ROBONEO_CLIENT_ID,
            "client_language": get_env("ROBONEO_LANG", "en"),
            "country_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
            "room_id": room_id,
        }
        init_resp = self.webapi("/workflow/canvas/init.json", json_body=init_body)
        # RoboneoMulti 1.0.8: init xong gọi canvas/info (bắt buộc trước nodeexecute)
        self.canvas_info(room_id)
        return init_resp

    def canvas_info(self, room_id: str) -> dict[str, Any]:
        return self.webapi(
            "/workflow/canvas/info.json",
            method="GET",
            params={
                "gnum": self.gid,
                "client_id": ROBONEO_CLIENT_ID,
                "client_language": get_env("ROBONEO_LANG", "en"),
                "country_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
                "room_id": room_id,
            },
        )

    def canvas_save(self, room_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        canvas_data = {
            "nodes": workflow.get("nodes") or [],
            "edges": workflow.get("edges") or [],
        }
        body = {
            "gnum": self.gid,
            "client_id": ROBONEO_CLIENT_ID,
            "client_language": get_env("ROBONEO_LANG", "en"),
            "country_code": get_env("ROBONEO_COUNTRY_CODE", "VN"),
            "room_id": room_id,
            "data": json.dumps(canvas_data, separators=(",", ":"), ensure_ascii=False),
        }
        return self.webapi("/workflow/canvas/save.json", json_body=body)

    def node_execute(
        self,
        room_id: str,
        workflow: dict[str, Any],
        *,
        api_name: str = MOTION_API_V26,
        prompt: str = "",
        model_pattern: str | None = None,
        surface: str | None = None,
    ) -> str:
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        nodes = workflow.get("nodes") or []
        main_node = next((n for n in nodes if n.get("type") == "VIDEO_EDIT_NODE"), None)
        text_node = next((n for n in nodes if n.get("type") == "TEXT_NODE"), None)
        video_node = next((n for n in nodes if n.get("type") == "VIDEO_NODE"), None)
        image_nodes = [n for n in nodes if n.get("type") == "IMAGE_NODE"]
        if not main_node:
            raise RoboNeoError("Workflow thiếu VIDEO_EDIT_NODE")

        main_node_id = str(main_node["id"])
        text_list = (text_node or {}).get("data", {}).get("textList") or [{"value": ""}]
        resolved_prompt = prompt or text_list[0].get("value") or "motion control"

        image_url = ""
        if image_nodes:
            image_list = (image_nodes[0].get("data") or {}).get("imageList") or []
            if image_list:
                image_url = str(image_list[0].get("originUrl") or image_list[0].get("url") or "")

        video_url = ""
        if video_node:
            video_list = (video_node.get("data") or {}).get("videoList") or []
            if video_list:
                video_url = str(video_list[0].get("originUrl") or video_list[0].get("url") or "")

        if not image_url or not video_url:
            raise RoboNeoError("Workflow thiếu image_url hoặc video_url")

        main_params = (main_node.get("data") or {}).get("parameters") or {}
        node_parameters: dict[str, Any] = {
            "prompt": resolved_prompt,
            "image_url": image_url,
            "video_url": video_url,
            "random": main_params.get("random") or generate_timestamp_rand(),
        }
        if cfg["workflow_version"] == "v2":
            tool_abstract: str | dict[str, str] = {"cn": "Motion Control", "en": ""}
        else:
            tool_abstract = MOTION_TOOL_ABSTRACT
        node_spec = {
            "name": api_name,
            "tree_id": MOTION_MCP_CATEGORY_ID,
            "tool_abstract_name": tool_abstract,
            "node_id": main_node_id,
            "parameters": node_parameters,
        }

        tracking = self._surface_tracking(surface, room_id)
        execute_extra: dict[str, Any] = {
            **tracking,
            "big_data_patch": {"position_type": cfg["position_type"]},
        }
        param = self._base_parameter(
            "nodeexecute",
            room_id=room_id,
            node_id=main_node_id,
            node_list_array=[[node_spec]],
            send_num=1,
            extra=execute_extra,
        )
        if cfg["workflow_version"]:
            param["workflow_version"] = cfg["workflow_version"]
        if cfg["use_canvas"]:
            param["node_list_data"] = {
                "nodes": workflow.get("nodes") or [],
                "edges": workflow.get("edges") or [],
            }
        body = {"parameter": param}
        url = f"{GATEWAY_BASE}/nodeexecute"
        r = self.session.post(url, json=body, headers=self._gateway_headers(), timeout=60)
        r.raise_for_status()
        data = r.json()
        code = data.get("error_code", 0)
        if code != 0:
            raise RoboNeoGatewayError(int(code), str(data.get("error_msg") or ""), data)
        param_out = data.get("parameter") or data
        tasks = param_out.get("tasks") or []
        if tasks:
            first = tasks[0]
            task_id = first.get("task_id") if isinstance(first, dict) else str(first)
        else:
            task_id = (
                param_out.get("task_id")
                or (param_out.get("data") or {}).get("task_id")
                or param_out.get("id")
                or ""
            )
        if not task_id:
            raise RoboNeoError(f"nodeexecute không trả task_id: {param_out}")
        return str(task_id)

    def node_execute_query(
        self, room_id: str, task_id: str, *, surface: str | None = None
    ) -> dict[str, Any]:
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        query_room_id = room_id if cfg["workflow_version"] == "v2" else ""
        tracking = self._surface_tracking(surface, room_id)
        query_extra: dict[str, Any] = {
            **tracking,
            "big_data_patch": {"position_type": cfg["position_type"]},
        }
        param = self._base_parameter(
            "nodeexecutequery",
            task_ids=[task_id],
            room_id=query_room_id,
            send_num=1,
            extra=query_extra,
        )
        if cfg["workflow_version"]:
            param["workflow_version"] = cfg["workflow_version"]
        body = {"parameter": param}
        url = f"{GATEWAY_BASE}/nodeexecutequery"
        r = self.session.post(url, json=body, headers=self._gateway_headers(), timeout=60)
        r.raise_for_status()
        data = r.json()
        code = data.get("error_code", 0)
        if code != 0:
            raise RoboNeoGatewayError(int(code), str(data.get("error_msg") or ""), data)
        param_out = data.get("parameter") or data
        tasks = param_out.get("tasks") or {}
        if isinstance(tasks, dict):
            return tasks.get(task_id) or param_out
        return param_out

    def wait_for_task(
        self,
        room_id: str,
        task_id: str,
        *,
        poll_sec: float = 5.0,
        timeout_sec: float = 3600.0,
        surface: str | None = None,
    ) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            data = self.node_execute_query(room_id, task_id, surface=surface)
            status = (
                data.get("state")
                or data.get("result_status")
                or (data.get("data") or {}).get("status")
                or data.get("status")
            )
            progress = data.get("progress")
            if progress is not None:
                print(f"  … progress {progress}")
            video_url = data.get("last_image_url") or (
                (data.get("initial_transferred_urls") or [None])[0]
            )
            if video_url:
                return data
            if str(status).upper() in {"FAILED", "FAIL", "ERROR"}:
                raise RoboNeoError(f"Task failed: {data}")
            if str(status).upper() in {"SUCCEED", "SUCCESS", "DONE", "10"} and not video_url:
                raise RoboNeoError(f"Task SUCCESS nhưng không có URL video: {data}")
            time.sleep(poll_sec)
        raise RoboNeoError(f"Timeout sau {timeout_sec}s (task_id={task_id})")

    def extract_video_url(self, result: dict[str, Any]) -> str:
        if result.get("last_image_url"):
            urls = result.get("initial_transferred_urls") or [result["last_image_url"]]
            if urls:
                return str(urls[0])
        for key in ("urls", "images"):
            vals = result.get(key) or (result.get("data") or {}).get(key) or []
            if vals:
                return str(vals[0])
        media_list = result.get("media_info_list") or (result.get("data") or {}).get("media_info_list") or []
        for item in media_list:
            url = (item or {}).get("media_data")
            if url:
                return str(url)
        task_result = (result.get("data") or {}).get("task_result") or (result.get("parameters") or {}).get("data", {}).get("task_result")
        if task_result:
            videos = task_result.get("videos") or []
            if videos:
                return str(videos[0].get("url") or videos[0].get("media_data") or "")
        raise RoboNeoError(f"Không tìm thấy URL video trong response: {json.dumps(result)[:500]}")

    def build_motion_workflow(
        self,
        image_path: str | Path,
        image_url: str,
        image_asset_id: int,
        video_path: str | Path,
        video_url: str,
        video_asset_id: int,
        *,
        prompt: str = "",
        api_name: str = MOTION_API_V26,
    ) -> dict[str, Any]:
        image_path = Path(image_path)
        video_path = Path(video_path)
        main_id = generate_node_id()
        text_id = generate_node_id()
        image_id = generate_node_id()
        video_id = generate_node_id()
        resolved_prompt = prompt or "motion control"
        rand = generate_timestamp_rand()

        image_entry = _media_entry(image_path, image_url)
        video_entry = _media_entry(video_path, video_url)

        nodes = [
            {
                "id": main_id,
                "type": "VIDEO_EDIT_NODE",
                "meta": {"position": {"x": 273.33331298828125, "y": -250.66665649414062}},
                "data": {
                    "mcpCategoriesId": MOTION_MCP_CATEGORY_ID,
                    "apiName": api_name,
                    "parameters": {
                        "prompt": resolved_prompt,
                        "random": rand,
                        "image_url": image_url,
                        "video_url": video_url,
                    },
                },
            },
            {
                "id": text_id,
                "type": "TEXT_NODE",
                "meta": {"position": {"x": -206.66668701171875, "y": -570.6666564941406}},
                "data": {
                    "size": {"width": 260, "height": 160},
                    "textList": [{"value": resolved_prompt}],
                },
            },
            {
                "id": image_id,
                "type": "IMAGE_NODE",
                "meta": {"position": {"x": -206.66668701171875, "y": -330.6666564941406}},
                "data": {"asset_id": image_asset_id, "imageList": [image_entry]},
            },
            {
                "id": video_id,
                "type": "VIDEO_NODE",
                "meta": {"position": {"x": -206.66668701171875, "y": -90.66665649414062}},
                "data": {"asset_id": video_asset_id, "videoList": [video_entry]},
            },
        ]
        edges = [
            {
                "sourceNodeID": text_id,
                "targetNodeID": main_id,
                "sourcePortID": f"port-output-TEXT-{text_id}",
                "targetPortID": f"port-input-{main_id}-TEXT-0-0",
            },
            {
                "sourceNodeID": image_id,
                "targetNodeID": main_id,
                "sourcePortID": f"port-output-IMAGE-{image_id}",
                "targetPortID": f"port-input-{main_id}-IMAGE-1-0",
            },
            {
                "sourceNodeID": video_id,
                "targetNodeID": main_id,
                "sourcePortID": f"port-output-VIDEO-{video_id}",
                "targetPortID": f"port-input-{main_id}-VIDEO-2-0",
            },
        ]
        return {"nodes": nodes, "edges": edges, "main_node_id": main_id}

    def run_motion_pipeline(
        self,
        image_path: str | Path,
        video_path: str | Path,
        *,
        output_path: str | Path | None = None,
        prompt: str = "",
        api_name: str = MOTION_API_V26,
        mode: str | None = None,
        surface: str | None = None,
        poll_sec: float = 5.0,
        timeout_sec: float = 3600.0,
    ) -> Path:
        self.ensure_session()
        surface = resolve_surface(surface)
        cfg = surface_config(surface)
        pattern_type = resolve_motion_mode(mode)
        mode_label = "std" if pattern_type == "normal" else "pro"
        print(
            f"→ surface {surface} | model {api_name} | mode {mode_label} "
            f"(model_pattern={pattern_type})"
        )
        print("→ initconfig …")
        self.init_config()
        print("→ meiyequery …")
        credit = self.meiye_query(surface=surface)
        print(
            f"  check_result={credit.get('check_result')} "
            f"amount={credit.get('amount')}"
        )
        if credit.get("check_result") is False:
            raise RoboNeoError(f"Không đủ credit: {credit}")
        print("→ createroom …")
        room_id = self.create_room(surface=surface)
        print(f"  room_id={room_id} (room_type={cfg['room_type']})")
        print("→ countcost …")
        cost = self.count_cost(
            api_name=api_name,
            room_id=room_id,
            model_pattern=pattern_type,
            surface=surface,
        )
        cost_item = (cost.get("items") or [{}])[0] if isinstance(cost, dict) else {}
        print(
            f"  cost={cost_item.get('cost')} real_cost={cost_item.get('real_cost')} "
            f"fallback={cost_item.get('fallback_cost')}"
        )
        fallback = cost_item.get("fallback_cost")
        if fallback and credit.get("amount") is not None and int(credit["amount"]) < int(fallback):
            print(
                f"⚠️ Credit {credit['amount']} < fallback {fallback} — job có thể bị hủy ngầm"
            )

        print("→ upload image …")
        image_up = self.upload_file(image_path, surface=surface)
        image_url = image_up["url"]
        print(f"  {image_url[:100]}… (asset_id={image_up['asset_id']})")
        print("→ upload video …")
        video_up = self.upload_file(video_path, surface=surface)
        video_url = video_up["url"]
        print(f"  {video_url[:100]}… (asset_id={video_up['asset_id']})")

        workflow = self.build_motion_workflow(
            image_path,
            image_url,
            image_up["asset_id"],
            video_path,
            video_url,
            video_up["asset_id"],
            prompt=prompt,
            api_name=api_name,
        )
        if cfg["use_canvas"]:
            print("→ canvas init/save …")
            self.canvas_init(room_id)
            self.canvas_save(room_id, workflow)
            self.canvas_info(room_id)

        print("→ nodeexecute …")
        task_id = self.node_execute(
            room_id,
            workflow,
            api_name=api_name,
            prompt=prompt,
            model_pattern=pattern_type,
            surface=surface,
        )
        print(f"  task_id={task_id}")

        print("→ poll …")
        result = self.wait_for_task(
            room_id,
            task_id,
            poll_sec=poll_sec,
            timeout_sec=timeout_sec,
            surface=surface,
        )
        video_out = self.extract_video_url(result)
        print(f"✅ {video_out}")

        out = Path(output_path or f"motion_{int(time.time())}.mp4")
        r = self.session.get(video_out, timeout=300)
        r.raise_for_status()
        out.write_bytes(r.content)
        return out
