"""WP-0k unit 3: the link in an analysis share email, through the running app.

Signs in as the WP-2c stack's admin, posts /api2/share/email with a forged Host
and hostile queryUrl values, and prints the link mailpit received.

    uv run --no-project --with requests python probe_share.py
"""

import subprocess

import requests

BASE = "http://127.0.0.1:58841"
WEB = "wp0k-host-web-1"


def admin_session():
    with open("/tmp/wp0k-stack/stack.env") as env:  # noqa: S108 (the local probe stack's env file)
        password = next(
            line.strip().split("=", 1)[1]
            for line in env
            if line.startswith("CONTRACT_PASSWORD=")
        )
    session = requests.Session()
    session.post(
        f"{BASE}/api2/authentication/login?set_cookie=true",
        json={
            "email": "contract-admin@harmony.invalid",
            "password": password,
            "remember_me": False,
        },
    ).raise_for_status()
    return session


def mailed():
    return subprocess.run(
        ["docker", "exec", WEB, "python", "/zenysis/probe_mail.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


QUERY_URLS = [
    "https://real.org/advanced-query#h=d41d8cd98f00b204",
    "https://attacker.invalid/advanced-query#h=d41d8cd98f00b204",
    "https://attacker.invalid/fr/advanced-query#h=d41d8cd98f00b204",
    "https://attacker.invalid/phish",
    'https://real.org/advanced-query#h="><a href="https://attacker.invalid/">x</a>',
]

session = admin_session()
mailed()
print("| queryUrl sent (Host: attacker.invalid) | Status | Link in the mail |")
print("|---|---|---|")
for query_url in QUERY_URLS:
    response = session.post(
        f"{BASE}/api2/share/email",
        headers={
            "Host": "attacker.invalid",
            "Cookie": f"accessKey={session.cookies['accessKey']}",
        },
        json={
            "subject": "WP-0k probe",
            "sender": "contract-admin@harmony.invalid",
            "message": "probe",
            "recipients": ["viewer@harmony.invalid"],
            "attachments": [],
            "queryUrl": query_url,
            "isPreview": False,
        },
    )
    link = mailed().split(" -> ", 1)[-1]
    print(f"| `{query_url}` | {response.status_code} | `{link}` |")
