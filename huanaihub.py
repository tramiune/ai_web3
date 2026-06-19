"""
Huan AI Hub (CMSNT SHOPCLONE) — mua nick RoboNeo qua API.

Docs: https://documenter.getpostman.com/view/9826758/TzzANcVu
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from project_env import get_env, load_project_env
from roboneo_proxy import proxy_dict_from_key

DEFAULT_BASE = "https://huanaihub.com"
DEFAULT_PRODUCT_ID = 138  # RoboNeo 120-140 Carot

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://huanaihub.com/",
    }
)


class HuanAiHubError(Exception):
    pass


@dataclass
class RoboNeoAccount:
    email: str
    password: str
    raw: str
    trans_id: str = ""
    product_name: str = ""


def _base_url() -> str:
    load_project_env()
    return (get_env("HUANAIHUB_BASE_URL", DEFAULT_BASE) or DEFAULT_BASE).rstrip("/")


def _credentials() -> tuple[str, str]:
    load_project_env()
    username = (get_env("HUANAIHUB_USERNAME") or get_env("HUANAIHUB_EMAIL") or "").strip()
    password = (get_env("HUANAIHUB_PASSWORD") or get_env("HUANAIHUB_API_KEY") or "").strip()
    if not username or not password:
        raise HuanAiHubError(
            "Thiếu HUANAIHUB_USERNAME + HUANAIHUB_PASSWORD (hoặc HUANAIHUB_API_KEY) trong .env"
        )
    return username, password


def _proxies() -> dict[str, str] | None:
    load_project_env()
    key = (get_env("HUANAIHUB_PROXY_KEY") or get_env("ROBONEO_PROXY_KEY") or "").strip()
    if not key:
        return None
    proxies, _ = proxy_dict_from_key(key)
    return proxies


def _request(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    username, password = _credentials()
    url = f"{_base_url()}{path}"
    merged = {"username": username, "password": password, **(params or {})}
    resp = _SESSION.get(url, params=merged, timeout=60, proxies=_proxies())
    if resp.status_code == 403:
        raise HuanAiHubError(
            "huanaihub trả 403 Forbidden — thử VPN/4G VN hoặc mở huanaihub.com trên browser trước"
        )
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as e:
        raise HuanAiHubError(f"Response không phải JSON: {resp.text[:200]}") from e
    if not isinstance(data, dict):
        raise HuanAiHubError(f"Response lạ: {data!r}")
    if data.get("status") != "success":
        msg = data.get("msg") or data.get("message") or str(data)
        raise HuanAiHubError(str(msg))
    return data


def get_balance() -> str:
    username, password = _credentials()
    url = f"{_base_url()}/api/GetBalance.php"
    resp = _SESSION.get(
        url,
        params={"username": username, "password": password},
        timeout=60,
        proxies=_proxies(),
    )
    if resp.status_code == 403:
        raise HuanAiHubError(
            "huanaihub trả 403 Forbidden — thử VPN/4G VN hoặc mở huanaihub.com trên browser trước"
        )
    resp.raise_for_status()
    text = resp.text.strip()
    try:
        data = resp.json()
    except ValueError:
        return text or "?"
    if isinstance(data, (int, float)):
        return str(int(data)) if float(data).is_integer() else str(data)
    if isinstance(data, str):
        return data
    if data.get("status") == "success":
        return str(data.get("balance") or data.get("data") or data.get("msg") or text)
    if data.get("status") == "error":
        raise HuanAiHubError(str(data.get("msg") or data))
    return text or str(data)


def list_products() -> list[dict[str, Any]]:
    data = _request("/api/ListResource.php")
    products: list[dict[str, Any]] = []
    for cat in data.get("categories") or []:
        for acc in cat.get("accounts") or []:
            row = dict(acc)
            row["category_id"] = cat.get("id")
            row["category_name"] = cat.get("name")
            products.append(row)
    return products


def product_info(product_id: int) -> dict[str, Any]:
    data = _request("/api/InfoResource.php", params={"id": product_id})
    rows = data.get("data")
    if isinstance(rows, list) and rows:
        return rows[0]
    if isinstance(rows, dict):
        return rows
    return data


def buy_product(product_id: int, amount: int = 1) -> dict[str, Any]:
    if amount < 1:
        raise HuanAiHubError("amount phải >= 1")
    return _request(
        "/api/BResource.php",
        params={"id": product_id, "amount": amount},
    )


def default_product_id() -> int:
    load_project_env()
    raw = (get_env("HUANAIHUB_PRODUCT_ID", str(DEFAULT_PRODUCT_ID)) or str(DEFAULT_PRODUCT_ID)).strip()
    return int(raw)


def find_roboneo_carrot_product(products: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = products if products is not None else list_products()
    pid = default_product_id()
    for item in items:
        if str(item.get("id")) == str(pid):
            return item
    for item in items:
        name = str(item.get("name") or "").lower()
        if "roboneo" in name and "carot" in name and int(item.get("amount") or 0) > 0:
            return item
    raise HuanAiHubError(f"Không tìm thấy sản phẩm RoboNeo carrot (id={pid}) còn hàng")


def parse_roboneo_account(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        raise HuanAiHubError("Account string rỗng")

    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            email = (
                obj.get("email")
                or obj.get("username")
                or obj.get("account")
                or obj.get("mail")
                or ""
            )
            password = obj.get("password") or obj.get("pass") or obj.get("pwd") or ""
            email = str(email).strip()
            password = str(password).strip()
            if email and password:
                return email, password

    for sep in ("|", "\t", ";"):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 2:
                email, password = parts[0], parts[1]
                if "@" in email or "outlook" in email.lower() or "gmail" in email.lower():
                    return email, password
                if "@" in parts[1]:
                    return parts[1], parts[0]

    if ":" in text:
        parts = [p.strip() for p in text.split(":") if p.strip()]
        if len(parts) >= 2:
            for i, part in enumerate(parts):
                if "@" in part:
                    email = part
                    rest = [p for j, p in enumerate(parts) if j != i]
                    password = rest[-1] if rest else ""
                    if password:
                        return email, password
            return parts[0], parts[1]

    m = re.search(r"([^\s|;:]+@[^\s|;:]+)\s*[,|]\s*(\S+)", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    raise HuanAiHubError(f"Không parse được account: {text[:80]!r}")


def buy_roboneo_account(
    *,
    product_id: int | None = None,
    amount: int = 1,
    save_path: Path | None = None,
) -> RoboNeoAccount:
    pid = product_id if product_id is not None else default_product_id()
    info = product_info(pid)
    stock = int(info.get("amount") or 0)
    if stock < amount:
        raise HuanAiHubError(
            f"Sản phẩm id={pid} ({info.get('name')}) hết hàng (còn {stock}, cần {amount})"
        )

    result = buy_product(pid, amount=amount)
    payload = result.get("data") or {}
    lists = payload.get("lists") or []
    if not lists:
        raise HuanAiHubError(f"Mua OK nhưng không có account trong response: {result}")

    raw_item = lists[0]
    raw = raw_item.get("account") if isinstance(raw_item, dict) else str(raw_item)
    email, password = parse_roboneo_account(str(raw))

    account = RoboNeoAccount(
        email=email,
        password=password,
        raw=str(raw),
        trans_id=str(payload.get("trans_id") or ""),
        product_name=str(payload.get("name") or info.get("name") or ""),
    )

    if save_path is None:
        save_path = Path(__file__).resolve().parent / "huanaihub_purchases.jsonl"
    record = {
        "trans_id": account.trans_id,
        "product_id": pid,
        "product_name": account.product_name,
        "email": account.email,
        "raw": account.raw,
    }
    with save_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return account
