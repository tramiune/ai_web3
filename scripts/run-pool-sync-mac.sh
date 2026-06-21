#!/usr/bin/env bash
# Sync pool RoboNeo từ Mac — chậm, tránh rate limit. Push/pull qua VPS Kaling.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VPS_HOST="${VPS_HOST:-165.101.46.68}"
VPS_USER="${VPS_USER:-root}"
VPS_PASS="${VPS_PASS:-}"
SHARED_POOL="${SHARED_POOL:-/root/shared/roboneo/account_pool.json}"
LOCK="${LOCK:-/root/shared/roboneo/.pool_sync.lock}"
LOCAL_POOL="${ROBONEO_POOL_FILE:-$ROOT/account_pool.json}"
LOG="${ROOT}/pool_sync_mac.log"

# Khuyên: 30s/nick + 10 phút pause khi 45130/10115 → ~6–8h cho 418 nick
SYNC_DELAY="${SYNC_DELAY:-30}"
SYNC_RATE_LIMIT_PAUSE="${SYNC_RATE_LIMIT_PAUSE:-600}"
SYNC_RATE_LIMIT_RETRIES="${SYNC_RATE_LIMIT_RETRIES:-2}"
SYNC_PROXY_RETRIES="${SYNC_PROXY_RETRIES:-3}"

ssh_vps() {
  if [[ -z "$VPS_PASS" ]]; then
    ssh -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}" "$@"
  else
    sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}" "$@"
  fi
}

scp_from_vps() {
  if [[ -z "$VPS_PASS" ]]; then
    scp -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}:$1" "$2"
  else
    sshpass -p "$VPS_PASS" scp -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}:$1" "$2"
  fi
}

cmd="${1:-help}"

case "$cmd" in
  pull)
    echo "==> Tải pool từ VPS → $LOCAL_POOL"
    scp_from_vps "$SHARED_POOL" "$LOCAL_POOL"
    python3 - <<PY
import json
d=json.load(open("$LOCAL_POOL"))
print("Local:", len(d.get("accounts") or []), "nick")
PY
    ;;

  pause-vps)
    echo "==> VPS: tạm bỏ RoboNeo (lock pool) — bot Kaling dùng VAE"
    ssh_vps "touch '$LOCK' && echo sync > '$LOCK' && rm -f /root/ai_web3/pool_sync.log 2>/dev/null; pgrep -af refresh_pool_credits || true; echo lock_ok"
    ;;

  sync)
    export ROBONEO_POOL_FILE="$LOCAL_POOL"
    echo "==> Sync local pool (log: $LOG)"
    echo "    delay=${SYNC_DELAY}s rate_pause=${SYNC_RATE_LIMIT_PAUSE}s retries=${SYNC_RATE_LIMIT_RETRIES} proxy_retries=${SYNC_PROXY_RETRIES}"
    echo "=== mac sync start $(date '+%Y-%m-%d %H:%M:%S %Z') ===" >> "$LOG"
    python3 scripts/refresh_pool_credits.py \
      --all --force-login \
      --delay "$SYNC_DELAY" \
      --rate-limit-pause "$SYNC_RATE_LIMIT_PAUSE" \
      --rate-limit-retries "$SYNC_RATE_LIMIT_RETRIES" \
      --proxy-retries "$SYNC_PROXY_RETRIES" \
      "${@:2}" 2>&1 | tee -a "$LOG"
    ec=${PIPESTATUS[0]}
    echo "=== mac sync end $(date '+%Y-%m-%d %H:%M:%S %Z') exit=$ec ===" >> "$LOG"
    exit "$ec"
    ;;

  push)
    echo "==> Upload pool lên VPS"
    VPS_PASS="${VPS_PASS:-}" VPS_HOST="$VPS_HOST" SRC="$LOCAL_POOL" bash "$ROOT/scripts/push-pool-to-vps.sh"
    ;;

  resume-vps)
    echo "==> VPS: gỡ lock — bot pick RoboNeo lại"
    ssh_vps "rm -f '$LOCK' && test ! -f '$LOCK' && echo lock_removed"
    ;;

  all)
    "$0" pull
    "$0" pause-vps
    "$0" sync
    "$0" push
    "$0" resume-vps
    ;;

  help|*)
    cat <<EOF
Usage: VPS_PASS='...' bash scripts/run-pool-sync-mac.sh <command>

Commands:
  pull        Tải pool 418 nick từ VPS về Mac
  pause-vps   VPS tạm không dùng RoboNeo (touch lock)
  sync        Chạy sync trên Mac (mặc định delay=${SYNC_DELAY}s)
  push        Upload pool đã sync lên VPS
  resume-vps  Gỡ lock — bật RoboNeo lại
  all         pull → pause → sync → push → resume

Tuỳ chỉnh tốc độ:
  SYNC_DELAY=45 SYNC_RATE_LIMIT_PAUSE=900 bash scripts/run-pool-sync-mac.sh sync

Chạy lại sau batch fail (bỏ nick locked):
  bash scripts/run-pool-sync-mac.sh sync -- --skip-locked

Chạy nền trên Mac:
  nohup bash scripts/run-pool-sync-mac.sh sync >> pool_sync_mac.log 2>&1 &
  tail -f pool_sync_mac.log
EOF
    ;;
esac
