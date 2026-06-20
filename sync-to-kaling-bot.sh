#!/bin/bash
# Đồng bộ code từ repo dev → ~/kaling-bot (deploy lên VPS; KHÔNG chạy bot trên Mac).
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/kaling-bot"
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude 'bot_chrome_profile' \
  --exclude 'bot_restart.log' --exclude 'bot_launchd.log' \
  "$SRC/" "$DST/"
echo "Synced → $DST"
echo "Bot chỉ chạy trên VPS — Mac launchd đã tắt (com.kaling.bot disabled)."
