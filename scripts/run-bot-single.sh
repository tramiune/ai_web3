#!/usr/bin/env bash
# Khởi động đúng 1 instance bot — kill cũ, đợi hết process, rồi start.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <bot_name> [--mode api|http|browser] [extra bot.py args...]"
  exit 1
fi

BOT_NAME="$1"
shift
PATTERN="bot.py --name ${BOT_NAME}"
SAFE="$(printf '%s' "$BOT_NAME" | tr -c '[:alnum:]_-' '_')"

echo "==> Dừng instance cũ: ${BOT_NAME}"
pkill -9 -f "${PATTERN}" 2>/dev/null || true
for _ in $(seq 1 25); do
  pgrep -f "${PATTERN}" >/dev/null 2>&1 || break
  sleep 1
done
if pgrep -f "${PATTERN}" >/dev/null 2>&1; then
  echo "❌ Không dừng được bot cũ:"
  pgrep -af "${PATTERN}" || true
  exit 1
fi

rm -f "${ROOT}/.run/bot-${SAFE}.lock" 2>/dev/null || true

export PYTHONUNBUFFERED=1
echo "==> Start bot: ${BOT_NAME} $*"
nohup python3 "${ROOT}/bot.py" --name "${BOT_NAME}" "$@" >> "${ROOT}/bot_restart.log" 2>&1 &
sleep 4
COUNT="$(pgrep -fc "${PATTERN}" 2>/dev/null || echo 0)"
if [ "${COUNT}" -ne 1 ]; then
  echo "❌ Cần đúng 1 process, đang có ${COUNT}:"
  pgrep -af "${PATTERN}" || true
  exit 1
fi
echo "✅ Bot ${BOT_NAME} — 1 instance (PID $(pgrep -f "${PATTERN}" | head -1))"
