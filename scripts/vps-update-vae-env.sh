#!/bin/bash
set -euo pipefail
cd /root/ai_web3
python3 <<'PY'
import re
from pathlib import Path

p = Path(".env")
text = p.read_text()
m = re.search(r"kaling@gmail\.com:([^,\n]+)", text)
pw = m.group(1) if m else "123456"
lines = [ln for ln in text.splitlines() if not ln.startswith("VIDEOAIEASY_")]
while lines and not lines[-1].strip():
    lines.pop()
lines.extend(
    [
        f"VIDEOAIEASY_ACCOUNTS=kaling@gmail.com:{pw}",
        "VIDEOAIEASY_MAX_CONCURRENT=50",
        "VIDEOAIEASY_SLOT_RETRY_SEC=20",
    ]
)
p.write_text("\n".join(lines) + "\n")
print("ENV_OK max=50 nick=kaling@gmail.com")
PY
bash scripts/run-bot-single.sh kaling_vps_bot --mode api
sleep 10
pgrep -af 'bot.py --name kaling_vps_bot' || echo NO_BOT
echo '---LOG---'
tail -22 /root/ai_web3/bot_restart.log
