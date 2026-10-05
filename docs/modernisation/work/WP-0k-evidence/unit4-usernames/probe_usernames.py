"""WP-0k unit 4: username matching through the running app (Postgres).

Run against the WP-2c stack (gunicorn on 127.0.0.1:58841, container
wp0k-host-web-1) with a run label, so each run uses fresh accounts:

    uv run --no-project --with requests python probe_usernames.py <label>

Creates `jane.doe.<label>` and `Mixed.Case.<label>` with scripts/create_user.py,
then signs in, invites and registers through the HTTP API and reports which
account each session belongs to. Passwords are random per run; tokens are never
printed.
"""

import base64
import json
import re
import secrets
import subprocess
import sys

import requests

BASE = "http://127.0.0.1:58841"
WEB = "wp0k-host-web-1"
LABEL = sys.argv[1]
DOMAIN = "harmony.invalid"
OLDER = f"jane.doe.{LABEL}@{DOMAIN}"
LOOK_ALIKE = f"jane_doe.{LABEL}@{DOMAIN}"
MIXED = f"Mixed.Case.{LABEL}@{DOMAIN}"


def secret_from_env_file(name):
    with open("/tmp/wp0k-stack/stack.env") as env:
        for line in env:
            if line.startswith(f"{name}="):
                return line.strip().split("=", 1)[1]
    raise KeyError(name)


def create_user(username, password):
    subprocess.run(
        ["docker", "exec", WEB, "python", "scripts/create_user.py",
         f"--username={username}", f"--password={password}",
         "--first_name=Probe", "--last_name=User", "--overwrite"],
        check=True, capture_output=True,
    )


def login(username, password):
    session = requests.Session()
    response = session.post(
        f"{BASE}/api2/authentication/login?set_cookie=true",
        json={"email": username, "password": password, "remember_me": False},
    )
    return session, response


def identity(session):
    token = session.cookies.get("accessKey")
    if not token:
        return None
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["identity"]


def whoami(session):
    page = session.get(f"{BASE}/overview").text
    match = re.search(r'"username": "([^"]+)"', page)
    return match.group(1) if match else "(not signed in)"


rows = []
older_password, mixed_password, look_alike_password = (
    secrets.token_urlsafe(16) + "aA1!" for _ in range(3)
)
create_user(OLDER, older_password)
create_user(MIXED, mixed_password)
admin, _ = login("contract-admin@harmony.invalid", secret_from_env_file("CONTRACT_PASSWORD"))

session, response = login(MIXED.lower(), mixed_password)
rows.append(("log in typing the username in lower case", response.status_code,
             identity(session), whoami(session)))

response = admin.post(f"{BASE}/api2/user/invite", json=[{"name": "Lookalike", "email": LOOK_ALIKE}])
rows.append((f"admin invites the look-alike {LOOK_ALIKE}", response.status_code, "", ""))
token = subprocess.run(
    ["docker", "exec", WEB, "python", "/zenysis/probe_token.py", LOOK_ALIKE],
    check=True, capture_output=True, text=True,
).stdout.strip()

registrant = requests.Session()
response = registrant.post(
    f"{BASE}/api2/authentication/register",
    json={"email": LOOK_ALIKE, "firstname": "Look", "lastname": "Alike",
          "password": look_alike_password, "invite_token": token},
)
rows.append(("the look-alike registers", response.status_code,
             identity(registrant), whoami(registrant)))

session, response = login(LOOK_ALIKE, look_alike_password)
rows.append(("the look-alike logs in with its own password", response.status_code,
             identity(session), whoami(session)))

session, response = login(OLDER, older_password)
rows.append(("the older account logs in", response.status_code,
             identity(session), whoami(session)))

response = admin.post(f"{BASE}/api2/user/invite", json=[{"name": "Again", "email": MIXED.upper()}])
pending = subprocess.run(
    ["docker", "exec", WEB, "python", "-c",
     "import sys; from sqlalchemy import create_engine, text; import os; "
     "e = create_engine(os.environ['SQLALCHEMY_DATABASE_URI']); "
     "print(e.execute(text('select count(*) from \"user\" where lower(username) = lower(:u)'), u=sys.argv[1]).scalar())",
     MIXED],
    check=True, capture_output=True, text=True,
).stdout.strip()
rows.append((f"admin invites {MIXED.upper()} (exists as {MIXED})", response.status_code,
             "", f"accounts equal to it ignoring case: {pending}"))

print(f"| Step (run `{LABEL}`) | Status | JWT identity | Signed in as |")
print("|---|---|---|---|")
for step, status, ident, who in rows:
    print(f"| {step} | {status} | `{ident or ''}` | {who} |")
