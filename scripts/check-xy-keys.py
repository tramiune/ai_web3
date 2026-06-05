#!/usr/bin/env python3
"""Kiểm tra credits từng XIAOYANG_API_KEYS (không in full key)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from project_env import load_project_env

load_project_env()

from xiaoyang_api import XiaoyangApiClient, XiaoyangApiError, load_api_keys

FAST_CR = 72
TURBO_CR = 206

def mask(k: str) -> str:
    k = k.strip()
    if len(k) <= 12:
        return k[:4] + "…"
    return k[:8] + "…" + k[-4:]


def main():
    keys = load_api_keys()
    print(f"Keys configured: {len(keys)}\n")
    print(f"{'#':<3} {'key':<18} {'email':<28} {'credits':>8}  fast  turbo")
    print("-" * 72)
    for i, key in enumerate(keys):
        try:
            me = XiaoyangApiClient(api_key=key).me()
            cr = int(me.get("credits") or 0)
            email = (me.get("email") or "?")[:28]
            ok_fast = "yes" if cr >= FAST_CR else "no"
            ok_turbo = "yes" if cr >= TURBO_CR else "no"
            print(f"{i:<3} {mask(key):<18} {email:<28} {cr:>8}  {ok_fast:>4}  {ok_turbo:>5}")
        except Exception as e:
            print(f"{i:<3} {mask(key):<18} ERROR: {e}")
    print("\nBot phân chia đơn XY mới: ít queue + đủ credit (Turbo/Fast).")
    print("Thêm key vào XIAOYANG_API_KEYS rồi restart bot để nhận key mới.")


if __name__ == "__main__":
    main()
