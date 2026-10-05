"""WP-0k unit 1: what Host does nginx-proxy 1.11.6 hand to the app?

Sends POST /api2/authentication/forgot_password through the stack's
nginx-proxy (HTTPS on 127.0.0.1:58843 with SNI real.org, HTTP on 58842) and
directly to gunicorn (58841), with raw request bytes so no client normalises
the Host. After each request it prints the link mailpit received. Tokens in
the link are redacted.
"""

import re
import socket
import ssl
import subprocess
import sys

BODY = b'{"email":"contract-admin@harmony.invalid"}'
PATH = "/api2/authentication/forgot_password"
WEB = sys.argv[1] if len(sys.argv) > 1 else "wp0k-host-web-1"


def raw_request(port, use_tls, host_header, target=PATH, extra=()):
    sock = socket.create_connection(("127.0.0.1", port), timeout=30)
    if use_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname="real.org")
    lines = [f"POST {target} HTTP/1.1"]
    if host_header is not None:
        lines.append(f"Host: {host_header}")
    lines += [
        "Content-Type: application/json",
        f"Content-Length: {len(BODY)}",
        "Connection: close",
        *extra,
    ]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + BODY)
    data = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()
    head = data.split(b"\r\n\r\n", 1)[0].decode(errors="replace").split("\r\n")
    status = head[0].split(" ", 2)[1] if head and " " in head[0] else "?"
    location = next((h for h in head if h.lower().startswith("location:")), "")
    return status, location


def mailed_links():
    out = subprocess.run(
        ["docker", "exec", WEB, "python", "/zenysis/probe_mail.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return re.sub(r"token=[^\s&]+", "token=<redacted>", out) or "(no mail)"


CASES = [
    # (label, port, tls, Host header, request target, extra headers)
    ("direct gunicorn", 58841, False, "attacker.invalid", PATH, ()),
    ("direct gunicorn", 58841, False, "real.org:@attacker.invalid", PATH, ()),
    ("direct gunicorn", 58841, False, "real.org", PATH, ("SCRIPT_NAME: @attacker.invalid",)),
    ("direct gunicorn", 58841, False, "real.org", "/@attacker.invalid" + PATH, ("SCRIPT_NAME: @attacker.invalid",)),
    ("nginx https", 58843, True, "real.org", PATH, ()),
    ("nginx https", 58843, True, "attacker.invalid", PATH, ()),
    ("nginx https", 58843, True, "real.org:@attacker.invalid", PATH, ()),
    ("nginx https", 58843, True, "real.org:443@attacker.invalid", PATH, ()),
    ("nginx https", 58843, True, "real.org@attacker.invalid", PATH, ()),
    ("nginx https", 58843, True, "Real.ORG:@attacker.invalid", PATH, ()),
    ("nginx https", 58843, True, "real.org:8443", PATH, ()),
    ("nginx https", 58843, True, "real.org.", PATH, ()),
    ("nginx https", 58843, True, "real.org", "https://attacker.invalid" + PATH, ()),
    ("nginx https", 58843, True, "real.org", "https://real.org:@attacker.invalid" + PATH, ()),
    ("nginx https", 58843, True, "attacker.invalid", "https://real.org" + PATH, ()),
    ("nginx https", 58843, True, "real.org", PATH, ("X-Forwarded-Host: attacker.invalid",)),
    ("nginx https", 58843, True, "real.org", PATH, ("SCRIPT_NAME: @attacker.invalid",)),
    ("nginx https", 58843, True, "real.org", PATH, ("Script-Name: @attacker.invalid",)),
    ("nginx https", 58843, True, "real.org", "/@attacker.invalid" + PATH, ("SCRIPT_NAME: @attacker.invalid",)),
    ("nginx http", 58842, False, "real.org", PATH, ()),
    ("nginx http", 58842, False, "real.org:@attacker.invalid", PATH, ()),
    ("nginx http", 58842, False, "attacker.invalid", PATH, ()),
]

print("| Path | Host header | Request target | Extra header | Status | Location | Mailed link |")
print("|---|---|---|---|---|---|---|")
mailed_links()  # start from an empty mailbox
for label, port, tls, host, target, extra in CASES:
    try:
        status, location = raw_request(port, tls, host, target, extra)
    except (ssl.SSLError, OSError) as error:
        status, location = f"error: {type(error).__name__}", ""
    links = mailed_links()
    shown_target = target if target != PATH else "(origin-form)"
    print(
        f"| {label} | `{host}` | `{shown_target}` | `{'; '.join(extra)}` | {status} "
        f"| `{location.split(':', 1)[1].strip() if location else ''}` | {links} |"
    )
