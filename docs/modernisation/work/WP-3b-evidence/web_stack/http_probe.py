"""HTTP probes run inside the web container: anonymous pages, then a cookie login."""

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5000"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)  # noqa: S310 (fixed http base)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=60) as r:
            payload = r.read()
            return r.status, payload
    except urllib.error.HTTPError as e:
        return e.code, e.read()


for path in ["/", "/login", "/api2/user", "/static/build/version.txt"]:
    status, _ = call("GET", path)
    print(f"anonymous GET {path} {status}")

status, payload = call(
    "POST",
    "/api2/authentication/login?set_cookie=true",
    {"email": sys.argv[1], "password": sys.argv[2]},
)
print("POST /api2/authentication/login", status)
for path in ["/api2/user", "/api2/role", "/overview", "/data-catalog"]:
    status, payload = call("GET", path)
    detail = ""
    if path.startswith("/api2") and status == 200:
        detail = f" ({len(json.loads(payload)) if payload.strip().startswith(b'[') else 'object'} items)"
    print(f"signed-in GET {path} {status}{detail}")
