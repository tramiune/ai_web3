#!/usr/bin/env bash
# Sync toàn bộ pool RoboNeo (2 nick/IP) — chạy nền trên VPS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
[ -f .env ] && . ./.env
set +a
LOG="${ROOT}/pool_sync.log"
exec >>"$LOG" 2>&1
echo "=== pool sync start $(date -Is) pid=$$ ==="
python3 scripts/refresh_pool_credits.py --all --force-login
echo "=== pool sync end $(date -Is) exit=$? ==="
