#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
pkill -f 'python3 bot.py --name kaling_vps_bot' 2>/dev/null || true
sleep 2
set -a
set +u
# .env có thể có dòng lỗi — bỏ qua, không chặn khởi động bot
source .env 2>/dev/null || true
set +a
export PYTHONUNBUFFERED=1
nohup python3 bot.py --name kaling_vps_bot --mode api >> bot_restart.log 2>&1 &
sleep 5
pgrep -af 'python3 bot.py --name kaling_vps_bot' || echo "NOT RUNNING"
tail -15 bot_restart.log
