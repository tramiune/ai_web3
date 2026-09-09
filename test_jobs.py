import sys
from aidancing_api import AidancingApiClient

api = AidancingApiClient()
try:
    jobs = api.list_jobs(page=0, size=5)
    items = jobs.get("items", [])
    if items:
        import pprint
        pprint.pprint(items[0])
    else:
        print("Không có items nào.")
except Exception as e:
    print("Lỗi:", e)
