#!/usr/bin/env bash
set -euo pipefail
cd ~/ai_web
git fetch origin main
git checkout main 2>/dev/null || git checkout -b main origin/main
git reset --hard origin/main

ENV_FILE=~/ai_web/.env
touch "$ENV_FILE"
merge_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}
merge_env XIAOYANG_API_KEYS "xy_ko9hMsOmczIfQgBeO6zv5Z9QqzR_QnMPHwOzFNmhmz8,xy_YArPW-t5vz1aZzPlBFddH8i1Lu9C8Y5rJeSN5KUqbJ0,xy_xrhgUR-HgUMCAelwb6hWee0ABRCgeBfLhZsIOG7-1Gg,xy_AruOOUmWLnuRfY8832XvvDbLEKmZN1RH_mo43pRXCyY"
merge_env XIAOYANG_DIRECT_WORKER_URL https://xiaoyang-direct-media.traderfinn0312.workers.dev
merge_env XIAOYANG_OPTION_KEY default
merge_env XIAOYANG_MOTION_ORIENTATION video
merge_env BOT_MIN_RENDER_SEC 300
sed -i 's/\r$//' "$ENV_FILE"

BOT_SESSION=bot-motionai-http
BOT_CMD='cd ~/ai_web && set -a && source .env && set +a && export BOT_CDP_URL=http://127.0.0.1:9222 && python3 bot.py --name motionai_vps_bot --mode api'

tmux kill-session -t "$BOT_SESSION" 2>/dev/null || true
sleep 1
tmux new-session -d -s "$BOT_SESSION" bash -lc "$BOT_CMD"

sleep 6
echo "=== $BOT_SESSION log ==="
tmux capture-pane -t "$BOT_SESSION" -p | tail -30
