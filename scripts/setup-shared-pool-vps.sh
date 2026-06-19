#!/usr/bin/env bash
set -euo pipefail
SHARED=/root/shared/roboneo
mkdir -p "$SHARED"
cp -f /root/ai_web/account_pool.json "$SHARED/account_pool.json"
COUNT=$(python3 -c "import json; print(len(json.load(open('$SHARED/account_pool.json')).get('accounts') or []))")
echo "Shared pool: $COUNT nick at $SHARED/account_pool.json"
for envf in /root/ai_web/.env /root/ai_web3/.env; do
  if grep -q '^ROBONEO_POOL_FILE=' "$envf" 2>/dev/null; then
    sed -i 's|^ROBONEO_POOL_FILE=.*|ROBONEO_POOL_FILE='"$SHARED/account_pool.json"'|' "$envf"
  else
    echo "ROBONEO_POOL_FILE=$SHARED/account_pool.json" >> "$envf"
  fi
  grep ROBONEO_POOL_FILE "$envf"
done
