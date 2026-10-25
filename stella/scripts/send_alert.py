"""Пример: python send_alert.py mexc-bot "просадка -5%"  (STELLA_URL, STELLA_API_KEY в окружении)"""
import json
import os
import sys
import urllib.request

url = os.environ.get("STELLA_URL", "http://127.0.0.1:8000") + "/alert"
req = urllib.request.Request(
    url, data=json.dumps({"source": sys.argv[1], "text": sys.argv[2], "speak": "--speak" in sys.argv}).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["STELLA_API_KEY"]})
print(urllib.request.urlopen(req, timeout=10).read().decode())
