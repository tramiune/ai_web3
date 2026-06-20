#!/bin/bash
# Chạy Kaling bot trên Mac — chỉ 1 instance (lock file + script).
set -eo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
  set -a
  set +u
  # shellcheck disable=SC1091
  source .env 2>/dev/null || true
  set +a
fi
exec ./scripts/run-bot-single.sh kaling_vps_bot --mode api
