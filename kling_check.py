#!/usr/bin/env python3
"""Kiểm tra login + UI Kling (giống kling_motion_demo --check)."""

from playwright.sync_api import sync_playwright

from kling_session import (
    launch_kling_context,
    motion_file_inputs,
    open_motion_control,
    profile_dir_for_account,
    set_model_version,
    set_resolution,
    wait_for_login,
    wait_for_motion_ui,
)
from kling_motion import load_kling_accounts
from project_env import load_project_env

load_project_env()


def main() -> int:
    accounts = load_kling_accounts()
    acc = accounts[0]
    profile = profile_dir_for_account(acc["id"], acc.get("profile_path"))
    print(f"Check nick: {acc['nick']} → {profile}")
    with sync_playwright() as p:
        context = launch_kling_context(p, profile_path=profile)
        page = context.pages[0] if context.pages else context.new_page()
        open_motion_control(page)
        wait_for_login(page)
        wait_for_motion_ui(page)
        set_model_version(page)
        set_resolution(page)
        inputs = motion_file_inputs(page)
        print(f"OK — {inputs.count()} file inputs | {page.url}")
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
