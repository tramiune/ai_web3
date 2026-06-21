#!/usr/bin/env bash
# Upload account_pool.json lên VPS Kaling (shared pool + ai_web3).
set -euo pipefail

VPS_HOST="${VPS_HOST:-165.101.46.68}"
VPS_USER="${VPS_USER:-root}"
VPS_PASS="${VPS_PASS:?Set VPS_PASS (password SSH root VPS)}"
SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)/account_pool.json}"
SHARED="/root/shared/roboneo/account_pool.json"
LOCAL_COPY="/root/ai_web3/account_pool.json"

if [[ ! -f "$SRC" ]]; then
  echo "Không thấy pool: $SRC"
  exit 1
fi

python3 - <<'PY' "$SRC"
import json, sys
path = sys.argv[1]
d = json.load(open(path))
active = [a for a in d.get("accounts", []) if a.get("status") == "active"]
ok = sum(1 for a in active if a.get("credits") is not None and int(a.get("credits")) >= 120)
print(f"Local pool: {len(d.get('accounts') or [])} nick | active≥120: {ok}")
PY

export VPS_HOST VPS_USER VPS_PASS SRC SHARED LOCAL_COPY

expect <<'EXPECT_EOF'
set timeout 120
set pass $env(VPS_PASS)
set host $env(VPS_HOST)
set user $env(VPS_USER)
set src $env(SRC)
set shared $env(SHARED)
set localcopy $env(LOCAL_COPY)

spawn ssh -o StrictHostKeyChecking=no ${user}@${host} "mkdir -p /root/shared/roboneo /root/ai_web3"
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  eof
}

spawn scp -o StrictHostKeyChecking=no $src ${user}@${host}:$shared
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  eof
}

spawn ssh -o StrictHostKeyChecking=no ${user}@${host} "cp -f $shared $localcopy && python3 - <<'PY'
import json
p='$shared'
d=json.load(open(p))
active=[a for a in d.get('accounts',[]) if a.get('status')=='active']
ok=sum(1 for a in active if a.get('credits') is not None and int(a.get('credits'))>=120)
print(f'VPS pool: {len(d.get(\"accounts\") or [])} nick | active≥120: {ok}')
PY
grep -q '^ROBONEO_POOL_FILE=' /root/ai_web3/.env 2>/dev/null && sed -i 's|^ROBONEO_POOL_FILE=.*|ROBONEO_POOL_FILE=$shared|' /root/ai_web3/.env || echo ROBONEO_POOL_FILE=$shared >> /root/ai_web3/.env
grep ROBONEO_POOL_FILE /root/ai_web3/.env
pkill -HUP -f 'bot.py --name kaling_vps_bot' 2>/dev/null || true"
expect {
  "password:" { send "$pass\r"; exp_continue }
  "Password:" { send "$pass\r"; exp_continue }
  eof
}
EXPECT_EOF

echo "==> Pool đã lên VPS: $SHARED"
