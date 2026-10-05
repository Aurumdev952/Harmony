# WP-0k unit 1: does nginx-proxy 1.11.6 forward the raw Host?

**No.** It forwards the normalised `$host`, rejects any Host that contains `@` with 400, and sends hosts it does not serve to a default server that answers 503. Reset-link poisoning is therefore not reachable through the stock Compose deployment. It is reachable wherever gunicorn is reached without nginx-proxy, or behind a proxy that forwards `$http_host`.

## Setup (2026-10-05)

- The WP-2c stack (`tests/contract/stack` at b6e49b8), project `wp0k-host`, built from this branch at 764c3d7 (before any WP-0k code change), in a scratch copy under `/tmp`. Mail goes to mailpit.
- `compose.nginx.yaml` (this directory) adds `nginxproxy/nginx-proxy:1.11.6-alpine@sha256:99376e95…c03364`, the image and digest in `docker-compose.yaml`. `web` gets `VIRTUAL_HOST=real.org` and `HSTS`, `SSL_POLICY` and `HTTPS_METHOD=redirect` as in `docker-compose.yaml`. A self-signed `real.org` certificate stands in for the Let's Encrypt one. nginx inside the image is 1.31.3.
- The `docker.sock` mount points at the rootless socket `/run/user/1000/docker.sock` on this host.
- `probe_hosts.py` writes each request byte by byte (TLS with SNI `real.org` on 127.0.0.1:58843, plain HTTP on 58842, and gunicorn directly on 58841), so no client normalises the Host. After each request, `probe_mail.py` (run inside `web`) prints the link mailpit received. Tokens are redacted.

## Result

See `probe-before.md`, produced by `uv run --no-project python probe_hosts.py`.

- **Direct to gunicorn, the link follows the Host and `SCRIPT_NAME`.**
  - `Host: attacker.invalid` mails `http://attacker.invalid/user/reset-password?token=…`.
  - `Host: real.org:@attacker.invalid` mails `http://real.org:@attacker.invalid/…`, which a browser opens on `attacker.invalid`.
  - gunicorn 20.0.4 copies a `SCRIPT_NAME` request header into the environ and strips it from the path. `POST /@attacker.invalid/api2/authentication/forgot_password` with `SCRIPT_NAME: @attacker.invalid` mails `http://real.org@attacker.invalid/user/reset-password?token=…`. When the path does not contain the header's value, gunicorn fails with a 500 (`IndexError` in `gunicorn/http/wsgi.py:183`).
- **Through nginx-proxy, the app only ever sees a served host.**
  - Any Host containing `@` (`real.org:@attacker.invalid`, `real.org:443@attacker.invalid`, `real.org@attacker.invalid`, mixed case) gets **400** from nginx, over HTTP and HTTPS. The same holds in an absolute-form request target. The premise in decision 0006, that nginx matches `real.org:@attacker.invalid` to the real vhost, does not hold for this nginx.
  - An unserved host (`attacker.invalid`) gets **503** from the default server. Over TLS without a served SNI, the handshake is rejected (`ssl_reject_handshake on`).
  - The upstream Host is rebuilt as `proxy_set_header Host $host$host_port;`, with `$host_port` empty on 80 and 443. So `real.org:8443` and `real.org.` reach the app as `real.org`.
  - An absolute-form target overrides the Host header: `POST https://real.org/… ` with `Host: attacker.invalid` reaches the app as `real.org`.
  - `X-Forwarded-Host: attacker.invalid` is passed upstream, but the app has no `ProxyFix`, so the link stays on `real.org`.
  - nginx drops the `SCRIPT_NAME` header (underscore) by default, so the same request through nginx gets 405 and no mail. `Script-Name` reaches gunicorn but is not mapped to `SCRIPT_NAME`.
- **A finding of its own:** behind TLS the app sees plain HTTP from nginx, so every `_external=True` link it mails today starts with `http://`. It works only because nginx answers 301 to https. Building links from `DEPLOYMENT_BASE_URL` (https by WP-0i's validation) fixes this too.

## Severity for the human

- **Stock deployment** (nginx-proxy 1.11.6 in front, gunicorn not published, SEC-1): **Low**. The fix is defence in depth.
- **Any deployment where gunicorn is reachable without nginx-proxy, or that sits behind another proxy forwarding the raw Host** (for example `proxy_set_header Host $http_host`): **High**. An anonymous `forgot_password` with a forged Host mails a working reset token to a host the attacker controls, for any account. This branch closes it in the app, whatever the proxy.
- Not probed: HTTP/2 `:authority` (nginx applies the same host validation, but it was not measured here).

## Generated nginx configuration, excerpt

```
29:map $server_port $host_port {
30:    default :$server_port;
        80 '';
        443 '';
81:proxy_set_header Host $host$host_port;
86:proxy_set_header X-Forwarded-Host $proxy_x_forwarded_host;
94:    server_name _; # This is just an invalid value which will never trigger on a real hostname.
103:    ssl_reject_handshake on;
105:        return 503;
122:    server_name real.org;
136:        return 301 https://$host$request_uri;
140:    server_name real.org;
```
