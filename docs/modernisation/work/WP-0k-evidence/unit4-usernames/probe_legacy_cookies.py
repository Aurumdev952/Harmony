"""WP-0k unit 4: cookies minted before WP-0k carry the identity the user typed.

Signs accessKey cookies the way flask-jwt-extended 3 does (HS256, `identity`
and `user_claims`) with the stack's JWT key, for identities a pre-WP-0k login
or registration would have minted, and reports whom the running app signs in.

    uv run --no-project --with requests --with pyjwt python probe_legacy_cookies.py
"""

import re
import time
import uuid

import jwt
import requests

BASE = "http://127.0.0.1:58841"


def jwt_key():
    with open("/tmp/wp0k-stack/stack.env") as env:
        for line in env:
            if line.startswith("JWT_SECRET_KEY="):
                return line.strip().split("=", 1)[1]
    raise KeyError("JWT_SECRET_KEY")


def legacy_cookie(identity):
    now = int(time.time())
    claims = {
        "iat": now, "nbf": now, "jti": str(uuid.uuid4()), "exp": now + 3600,
        "identity": identity, "fresh": False, "type": "access",
        "user_claims": {"needs": ["*"], "query_needs": ["*"], "remember_me": False},
    }
    token = jwt.encode(claims, jwt_key(), algorithm="HS256")
    return token.decode() if isinstance(token, bytes) else token  # PyJWT 1 or 2


def whoami(identity):
    page = requests.get(f"{BASE}/overview", cookies={"accessKey": legacy_cookie(identity)}).text
    match = re.search(r'"username": "([^"]+)"', page)
    return match.group(1) if match else "(not signed in)"


CASES = [
    ("typed in lower case at login", "mixed.case.before@harmony.invalid"),
    ("typed as stored", "Mixed.Case.before@harmony.invalid"),
    ("minted by the look-alike's registration", "jane_doe.before@harmony.invalid"),
    ("the older account", "jane.doe.before@harmony.invalid"),
    ("a LIKE wildcard", "jane%before@harmony.invalid"),
    ("equal ignoring case to two accounts", "MIXED.CASE.BEFORE@HARMONY.INVALID"),
]

print("| Pre-WP-0k cookie | JWT identity | Signed in as |")
print("|---|---|---|")
for label, identity in CASES:
    print(f"| {label} | `{identity}` | {whoami(identity)} |")
