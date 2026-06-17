"""Playwright session cho Kling AI chính chủ (kling.ai)."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright

from project_env import get_env, load_project_env

load_project_env()

PROJECT_DIR = Path(__file__).resolve().parent
KLING_ORIGIN = get_env("KLING_ORIGIN", "https://kling.ai").rstrip("/")
KLING_DEFAULT_MODEL = get_env("KLING_MODEL_VERSION", "2.6").strip()
KLING_DEFAULT_RESOLUTION = get_env("KLING_RESOLUTION", "720p").strip().lower()
KLING_DEFAULT_ORIENTATION = get_env("KLING_CHARACTER_ORIENTATION", "video").strip().lower()
from kling_pricing import KLING_MAX_VIDEO_SEC
MOTION_CONTROL_URL = get_env(
    "KLING_MOTION_CONTROL_URL",
    f"{KLING_ORIGIN}/app/video-motion-control/new",
)
DEFAULT_PROFILES_ROOT = PROJECT_DIR / "kling_profiles"

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {}, loadTimes: function() {}, csi: function() {} };
"""


@dataclass
class KlingNetworkEvent:
    method: str
    url: str
    status: int
    body: object | None = None


@dataclass
class KlingNetworkSniffer:
    events: list[KlingNetworkEvent] = field(default_factory=list)
    max_events: int = 200

    def attach(self, page: Page) -> None:
        page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        url = (response.url or "").lower()
        if not any(
            token in url
            for token in (
                "/api/",
                "upload",
                "task",
                "work",
                "generate",
                "motion",
                "asset",
                "history",
            )
        ):
            return
        body = None
        try:
            if "json" in (response.headers.get("content-type") or "").lower():
                body = response.json()
        except Exception:
            body = None
        self.events.append(
            KlingNetworkEvent(
                method=response.request.method,
                url=response.url,
                status=response.status,
                body=body,
            )
        )
        if len(self.events) > self.max_events:
            self.events.pop(0)


def profile_dir_for_account(account_id: str, profile_path: str | None = None) -> Path:
    if profile_path:
        return Path(profile_path).resolve()
    return (DEFAULT_PROFILES_ROOT / account_id).resolve()


def _chrome_args() -> list[str]:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if get_env("KLING_CHROME_OFFSCREEN", "0") == "1":
        args.append("--window-position=-2400,-2400")
    return args


def launch_kling_context(playwright: Playwright, *, profile_path: Path) -> BrowserContext:
    cdp_url = get_env("KLING_CDP_URL", "").strip()
    if cdp_url:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            locale="en-US",
            timezone_id="Asia/Ho_Chi_Minh",
            viewport={"width": 1400, "height": 900},
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        print(f"🔗 Kling CDP: {cdp_url}")
        return context

    profile_path.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(profile_path),
        headless=get_env("KLING_HEADLESS", "0") == "1",
        slow_mo=int(get_env("KLING_SLOW_MO", "200")),
        ignore_default_args=["--enable-automation"],
        args=_chrome_args(),
        viewport={"width": 1400, "height": 900},
        locale="en-US",
        timezone_id="Asia/Ho_Chi_Minh",
    )
    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception as exc:
        print(f"⚠️ Không mở Chrome ({exc}) — dùng Chromium...")
        context = playwright.chromium.launch_persistent_context(**kwargs)
    context.add_init_script(STEALTH_INIT_SCRIPT)
    print(f"🌐 Kling profile: {profile_path}")
    return context


def open_motion_control(page: Page) -> None:
    page.goto(MOTION_CONTROL_URL, timeout=90_000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    ensure_motion_control_page(page)


def ensure_motion_control_page(page: Page) -> None:
    if "video-motion-control" not in (page.url or "").lower():
        page.goto(MOTION_CONTROL_URL, timeout=90_000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)


def _file_input_locator(page: Page):
    for selector in ("input.el-upload__input", "input[type='file']"):
        loc = page.locator(selector)
        if loc.count() >= 2:
            return loc
    return page.locator("input[type='file']")


def is_logged_in(page: Page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    if "sign in to view your assets" in body or "one-click sign in" in body:
        return False
    if _file_input_locator(page).count() >= 2:
        return True
    if page.get_by_role("combobox").count() > 0 and "sign in" not in body[:600]:
        return True
    return False


def wait_for_login(page: Page, timeout_sec: int = 300) -> None:
    if is_logged_in(page):
        print("✅ Đã đăng nhập Kling")
        return
    print("👉 Đăng nhập Kling trên cửa sổ Chrome (Google / email).")
    print(f"   URL: {page.url}")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        if is_logged_in(page):
            print("✅ Đăng nhập Kling xong")
            ensure_motion_control_page(page)
            return
    raise TimeoutError("Hết thời gian chờ đăng nhập Kling")


def wait_for_motion_ui(page: Page, timeout_sec: int = 90) -> None:
    ensure_motion_control_page(page)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _file_input_locator(page).count() >= 2:
            return
        if page.get_by_role("combobox").count() > 0:
            page.wait_for_timeout(1500)
            if _file_input_locator(page).count() >= 2:
                return
        page.wait_for_timeout(1000)
    raise TimeoutError(f"Motion Control chưa có ô upload — URL: {page.url}")


def motion_file_inputs(page: Page):
    wait_for_motion_ui(page)
    inputs = _file_input_locator(page)
    if inputs.count() < 2:
        raise RuntimeError(f"Không thấy đủ 2 ô upload trên {page.url}")
    return inputs


def set_model_version(page: Page, version: str | None = None) -> None:
    ver = (version or KLING_DEFAULT_MODEL or "2.6").strip()
    label = f"VIDEO {ver}"
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        opened = False
        for selector in (
            ".el-select .el-select__wrapper",
            ".el-select",
            ".el-select__selected-item",
        ):
            loc = page.locator(selector)
            if loc.count() > 0:
                loc.first.click(timeout=8000, force=True)
                opened = True
                break
        if not opened:
            page.get_by_role("combobox").first.click(timeout=8000, force=True)
        page.wait_for_timeout(600)
        page.get_by_role(
            "option",
            name=re.compile(rf"VIDEO\s+{re.escape(ver)}\b", re.I),
        ).first.click(timeout=10_000, force=True)
        page.wait_for_timeout(600)
        print(f"✅ Model: {label}")
    except Exception as exc:
        print(f"⚠️ Không chọn được model {label}: {exc}")


def set_orientation(page: Page, orientation: str | None = None) -> None:
    o = (orientation or KLING_DEFAULT_ORIENTATION or "video").strip().lower()
    label = (
        "Character Orientation Matches Image"
        if o in ("image", "img", "photo")
        else "Character Orientation Matches Video"
    )
    try:
        page.get_by_text("Matches Video" if o != "image" else "Matches Image").first.click(
            timeout=10_000
        )
        page.wait_for_timeout(500)
        print(f"✅ Orientation: {label}")
    except Exception as exc:
        print(f"⚠️ Không click được orientation ({exc})")


def set_resolution(page: Page, resolution: str | None = None) -> None:
    res = (resolution or KLING_DEFAULT_RESOLUTION or "720p").strip().lower()
    if res != "720p":
        print(f"⚠️ Chỉ dùng 720p — bỏ qua {res}")
    try:
        body = page.locator("body").inner_text(timeout=5000)
        if re.search(r"720p\s*·", body, re.I):
            print("✅ Resolution: 720p (đã chọn)")
            return
        page.get_by_text(re.compile(r"720p", re.I)).first.click(timeout=5000)
        page.wait_for_timeout(400)
        print("✅ Resolution: 720p")
    except Exception as exc:
        print(f"⚠️ Không chọn được 720p: {exc}")
