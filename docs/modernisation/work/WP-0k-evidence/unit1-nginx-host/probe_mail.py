"""Print the links in every message mailpit holds, then delete them (WP-0k unit 1)."""

import re
import sys

import requests

API = "http://mailpit:8025/api/v1"
messages = requests.get(f"{API}/messages", timeout=5).json()["messages"]
for summary in reversed(messages):
    message = requests.get(f"{API}/message/{summary['ID']}", timeout=5).json()
    body = (message.get("HTML") or "") + (message.get("Text") or "")
    links = sorted(set(re.findall(r'https?://[^\s"\'<>]+', body)))
    links = [
        link
        for link in links
        if "token=" in link or "/dashboard/" in link or "advanced-query" in link
    ]
    print(summary["Subject"], "->", " ".join(links) or "(no link)")
if "--keep" not in sys.argv:
    requests.delete(f"{API}/messages", timeout=5)
