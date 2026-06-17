#!/usr/bin/env python3
"""Deploy nhánh bot_kling — web kaling.cloud (wrangler) + bot Kling trên VPS."""
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
    "kling_session.py",
    "kling_motion.py",
    "kling_pricing.py",
    "kling_check.py",
    "tool98_api.py",
    "project_env.py",
    "user_order_notes.py",
    "xiaoyang_direct.py",
    "requirements.txt",
]


def run_ssh(ssh: paramiko.SSHClient, cmd: str, timeout: int = 300) -> tuple[int, str]:
    print(">", cmd)
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:", err.rstrip())
    return code, out


def ensure_env_kling(ssh: paramiko.SSHClient) -> None:
    patch = r"""
from pathlib import Path
p = Path('/root/ai_web3/.env')
lines = p.read_text(encoding='utf-8').splitlines() if p.exists() else []
updates = {
    'KLING_COINS_PER_SEC': '0.6',
    'KLING_MAX_VIDEO_SEC': '30',
    'KLING_MIN_VIDEO_SEC': '3',
    'KLING_MODEL_VERSION': '2.6',
    'KLING_RESOLUTION': '720p',
    'KLING_CHARACTER_ORIENTATION': 'video',
    'KLING_HEADLESS': '1',
    'KLING_MAX_CONCURRENT': '1',
}
if not any(l.startswith('KLING_ACCOUNTS=') for l in lines):
    updates['KLING_ACCOUNTS'] = 'default'
keys = {k for k in updates}
out = []
seen = set()
for line in lines:
    key = line.split('=', 1)[0].strip() if '=' in line else ''
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
print('KLING .env ok')
"""
    run_ssh(ssh, f"python3 - <<'PY'\n{patch}\nPY")


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=30)

    run_ssh(ssh, f"mkdir -p {REMOTE}/public {REMOTE}/kling_profiles/default")
    sftp = ssh.open_sftp()
    for name in ROOT_FILES:
        local = LOCAL / name
        if not local.is_file():
            print(f"SKIP missing {name}")
            continue
        print(f"Upload {name}")
        sftp.put(str(local), f"{REMOTE}/{name}")

  # public for wrangler source + VPS mirror
    for path in sorted((LOCAL / "public").rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(LOCAL / "public").as_posix()
        remote = f"{REMOTE}/public/{rel}"
        parent = os.path.dirname(remote)
        try:
            sftp.stat(parent)
        except OSError:
            run_ssh(ssh, f"mkdir -p {parent}")
        print(f"Upload public/{rel}")
        sftp.put(str(path), remote)
    sftp.close()

    sa_local = LOCAL.parent / "ai_web" / "serviceAccountKey.json"
    if sa_local.is_file():
        try:
            sftp = ssh.open_sftp()
            sftp.put(str(sa_local), f"{REMOTE}/serviceAccountKey.json")
            sftp.close()
            print("Uploaded serviceAccountKey.json")
        except Exception as exc:
            print(f"serviceAccountKey: {exc}")

    ensure_env_kling(ssh)
    run_ssh(ssh, f"cd {REMOTE} && pip3 install -r requirements.txt -q")
    run_ssh(
        ssh,
        "python3 -m playwright install chromium 2>/dev/null || "
        "python3 -m playwright install chrome 2>/dev/null || true",
        timeout=600,
    )
    run_ssh(ssh, f"pkill -f 'bot.py.*{BOT_NAME}' || true")
    run_ssh(ssh, "sleep 2")
    run_ssh(
        ssh,
        f"cd {REMOTE} && set -a && source .env && set +a && "
        f"nohup python3 -u bot.py --name {BOT_NAME} > /tmp/kaling_bot.log 2>&1 &",
    )
    run_ssh(ssh, "sleep 4")
    run_ssh(ssh, f"pgrep -af 'bot.py.*{BOT_NAME}' || echo NOT_RUNNING")
    run_ssh(ssh, "tail -30 /tmp/kaling_bot.log")
    run_ssh(
        ssh,
        f"grep -n 'KLING_COINS_PER_SEC\\|kling_motion\\|Kling 2.6' {REMOTE}/bot.py | head -5",
    )
    ssh.close()

    print("\n=== Wrangler deploy kaling.cloud ===")
    deploy = subprocess.run(
        ["npx", "wrangler", "deploy"],
        cwd=str(LOCAL),
        shell=True,
    )
    if deploy.returncode != 0:
        print("WARN: wrangler deploy failed — chạy tay: cd ai_web3 && npx wrangler deploy")
        return deploy.returncode

    print("\nDone. Bật bot trên Admin → Bots → kaling_vps_bot")
    print("Lần đầu: SSH VPS login Kling — cd /root/ai_web3 && python3 kling_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
