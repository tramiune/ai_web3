#!/bin/bash
# Deploy Kaling bot lên VPS mới (chạy từ Mac).
set -euo pipefail

VPS_HOST="${VPS_HOST:-165.101.46.68}"
VPS_USER="${VPS_USER:-root}"
VPS_PASS="${VPS_PASS:?Set VPS_PASS}"
SRC="${SRC:-$HOME/kaling-bot}"
REMOTE_DIR="${REMOTE_DIR:-/root/ai_web3}"

if ! command -v expect >/dev/null; then
  echo "Cần expect (macOS có sẵn)."
  exit 1
fi

echo "==> Dừng bot Mac (nếu còn chạy)..."
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.kaling.bot.plist" 2>/dev/null || true
pkill -f "python3 bot.py --name kaling_vps_bot" 2>/dev/null || true

echo "==> Kiểm tra SSH $VPS_USER@$VPS_HOST ..."
export VPS_HOST VPS_USER VPS_PASS
expect <<'EXPECT_EOF'
set timeout 60
set host $env(VPS_HOST)
set user $env(VPS_USER)
set pass $env(VPS_PASS)
spawn ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 ${user}@${host} "echo SSH_OK && uname -a"
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  "SSH_OK" { }
  timeout { puts "\nVPS chưa online — bật máy trên panel (Suspended → Running) rồi chạy lại."; exit 1 }
  eof
}
EXPECT_EOF

echo "==> Cài dependency trên VPS ..."
expect <<'EXPECT_EOF'
set timeout 600
set host $env(VPS_HOST)
set user $env(VPS_USER)
set pass $env(VPS_PASS)
spawn ssh -o StrictHostKeyChecking=no ${user}@${host} {bash -s}
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  -re {\$ |# } { }
}
send "export DEBIAN_FRONTEND=noninteractive\r"
expect -re {\$ |# }
send "apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv git rsync libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2\r"
expect -re {\$ |# }
send "mkdir -p /root/ai_web3\r"
expect -re {\$ |# }
send "exit\r"
expect eof
EXPECT_EOF

echo "==> Upload code + secrets ..."
export SRC REMOTE_DIR
expect <<'EXPECT_EOF'
set timeout 900
set host $env(VPS_HOST)
set user $env(VPS_USER)
set pass $env(VPS_PASS)
set src $env(SRC)
set remote $env(REMOTE_DIR)
spawn rsync -az --delete --exclude .git --exclude __pycache__ --exclude bot_chrome_profile --exclude bot_launchd.log --exclude bot_restart.log -e {ssh -o StrictHostKeyChecking=no} $src/ ${user}@${host}:${remote}/
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  eof
}
EXPECT_EOF

echo "==> pip + playwright + start bot ..."
expect <<'EXPECT_EOF'
set timeout 900
set host $env(VPS_HOST)
set user $env(VPS_USER)
set pass $env(VPS_PASS)
spawn ssh -o StrictHostKeyChecking=no ${user}@${host} {bash -s}
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  -re {\$ |# } { }
}
send "cd /root/ai_web3\r"
expect -re {\$ |# }
send "pip3 install -q -r requirements.txt\r"
expect -re {\$ |# }
send "python3 -m playwright install chromium\r"
expect -re {\$ |# }
send "bash scripts/run-bot-single.sh kaling_vps_bot --mode api\r"
expect -re {\$ |# }
send "sleep 5 && pgrep -af 'bot.py --name kaling_vps_bot' && tail -15 bot_restart.log\r"
expect -re {\$ |# }
send "exit\r"
expect eof
EXPECT_EOF

echo "==> Xong. Log: ssh root@$VPS_HOST 'tail -f /root/ai_web3/bot_restart.log'"
