#!/bin/bash
# Chạy Kaling bot trên Mac (một instance duy nhất — không chạy song song VPS).
set -eo pipefail
cd "$(dirname "$0")"
if pgrep -f "python3 bot.py --name kaling_vps_bot" >/dev/null 2>&1; then
  echo "Kaling bot đã chạy: $(pgrep -f 'python3 bot.py --name kaling_vps_bot' | head -1)"
  exit 0
fi
set -a
set +u
source .env
set -u
set +a
export PYTHONUNBUFFERED=1
nohup python3 bot.py --name kaling_vps_bot --mode api >> bot_restart.log 2>&1 &
echo "Started Kaling bot PID $!"
