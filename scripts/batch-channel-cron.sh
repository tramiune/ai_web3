#!/usr/bin/env bash
# Batch kênh TikTok (Kaling) — giờ chạy cấu hình trên web (cronHour).
# Crontab VPS: CRON_TZ=Asia/Ho_Chi_Minh
#   0 * * * * .../batch-channel-cron.sh >> .../logs/batch-channel.log 2>&1

set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
export PYTHONUNBUFFERED=1
python3 batch_channel.py --daily-hourly
