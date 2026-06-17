#!/usr/bin/env python3
"""Khôi phục VPS kaling_vps_bot về code nhánh main (VAE/XiaoYang), không phải bot_kling."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import paramiko

HOST = "165.101.46.68"
USER = "root"
PASS = "AZvpsQ!Y!4773kd"
REMOTE = "/root/ai_web3"
BOT_NAME = "kaling_vps_bot"
LOCAL = Path(__file__).resolve().parents[1]

ROOT_FILES = [
    "bot.py",
    "xiaoyang_motion.py",
    "xiaoyang_web.py",
    "xiaoyang_api.py",
    "xiaoyang_media.py",
    "xiaoyang_direct.py",
    "videoaieasy_web.py",
    "tool98_api.py",
    "aidancing_api.py",
    "project_env.py",
    "user_order_notes.py",
    "requirements.txt",
]


def git_bytes(rel: str, branch: str = "main") -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{branch}:{rel}"],
        cwd=str(LOCAL),
    )


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 180) -> None:
    print(">", cmd)
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:", err.rstrip())


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=30)

    sftp = ssh.open_sftp()
    for name in ROOT_FILES:
        try:
            data = git_bytes(name)
        except subprocess.CalledProcessError:
            print(f"SKIP missing on main: {name}")
            continue
        remote = f"{REMOTE}/{name}"
        print(f"Restore {name} ({len(data)} bytes)")
        with sftp.file(remote, "wb") as f:
            f.write(data)
    sftp.close()

    run(ssh, f"pkill -f 'bot.py.*{BOT_NAME}' || true")
    run(ssh, "sleep 2")
    run(
        ssh,
        f"cd {REMOTE} && set -a && source .env && set +a && "
        f"nohup python3 -u bot.py --name {BOT_NAME} --mode api > /tmp/kaling_bot.log 2>&1 &",
        timeout=15,
    )
    run(ssh, "sleep 4")
    run(ssh, f"pgrep -af '{BOT_NAME}' || echo NOT_RUNNING")
    run(ssh, "tail -20 /tmp/kaling_bot.log")
    run(ssh, f"grep -n 'VideoAiEasy\\|xiaoyang_motion' {REMOTE}/bot.py | head -3")
    ssh.close()
    print("VPS restored to main bot (VAE).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
