#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
  set -a
  set +u
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi
./scripts/run-bot-single.sh kaling_vps_bot --mode api
tail -15 bot_restart.log
