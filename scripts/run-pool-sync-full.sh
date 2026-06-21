#!/usr/bin/env bash
# Sync toàn bộ pool RoboNeo (2 nick/IP) — chạy nền trên VPS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="${ROOT}/pool_sync.log"
{
  echo "=== pool sync start $(date -Is) pid=$$ ==="
  set -a
  if [ -f .env ]; then
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
  fi
  set +a
  python3 scripts/refresh_pool_credits.py --all --force-login
  ec=$?
  echo "=== pool sync end $(date -Is) exit=$ec ==="
  exit "$ec"
} >>"$LOG" 2>&1
