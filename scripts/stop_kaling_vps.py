#!/usr/bin/env python3
"""Dừng bot kaling_vps_bot trên VPS."""
import paramiko

HOST = "165.101.46.68"
USER = "root"
PASS = "AZvpsQ!Y!4773kd"
BOT_NAME = "kaling_vps_bot"


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=30)
    for cmd in (
        f"pkill -f 'bot.py.*{BOT_NAME}' || true",
        "sleep 2",
        f"pgrep -af '{BOT_NAME}' || echo STOPPED",
    ):
        print(">", cmd)
        _i, o, e = ssh.exec_command(cmd, timeout=20)
        print(o.read().decode("utf-8", "replace").rstrip())
    ssh.close()
    print("VPS bot stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
