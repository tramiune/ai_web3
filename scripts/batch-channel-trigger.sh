#!/usr/bin/env bash
# Poll Firestore runNowRequestedAt — admin bấm「Chạy thử ngay」trên web.
# Crontab: * * * * * /root/ai_web3/scripts/batch-channel-trigger.sh >> /root/ai_web3/logs/batch-channel-trigger.log 2>&1

set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
export PYTHONUNBUFFERED=1
exec python3 batch_channel.py --poll-trigger
