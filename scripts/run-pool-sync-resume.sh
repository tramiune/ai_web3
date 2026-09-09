#!/usr/bin/env bash
# Tiếp tục sync pool — bỏ nick đã có credit + last_sync_at (không force-login lại).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${ROOT}/pool_sync.log"
DELAY="${RESUME_DELAY:-10}"
RATE_PAUSE="${SYNC_RATE_LIMIT_PAUSE:-600}"
{
  echo "=== pool sync RESUME start $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$ delay=${DELAY}s ==="
  python3 scripts/refresh_pool_credits.py \
    --resume --skip-locked \
    --delay "$DELAY" \
    --rate-limit-pause "$RATE_PAUSE" \
    --rate-limit-retries "${SYNC_RATE_LIMIT_RETRIES:-2}" \
    --proxy-retries "${SYNC_PROXY_RETRIES:-3}"
  ec=$?
  echo "=== pool sync RESUME end $(date '+%Y-%m-%d %H:%M:%S %Z') exit=$ec ==="
  exit "$ec"
} >>"$LOG" 2>&1
