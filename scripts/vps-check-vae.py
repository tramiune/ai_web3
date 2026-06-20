from project_env import get_env
from xiaoyang_motion import VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT, load_videoaieasy_accounts

accounts = load_videoaieasy_accounts()
print(f"accounts={len(accounts)} max={VIDEOAIEASY_MAX_CONCURRENT_PER_ACCOUNT}")
for a in accounts:
    print(f"  {a.get('email')}")
