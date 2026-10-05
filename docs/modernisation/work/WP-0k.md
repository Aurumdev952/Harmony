---
wp: "0k"
title: "Build outgoing links from the configured origin; match usernames exactly"
status: building
owner_role: "backend"
instances:
  - name: "backend-0k"
    files:
      - web/server/routes/views/page_renderer.py
      - web/server/routes/views/admin.py
      - web/server/routes/views/invite.py
      - web/server/routes/views/dashboard.py
      - web/server/routes/views/users.py
      - web/server/api/permission_api_models.py
      - web/server/api/dashboard_api_models.py
      - web/server/api/authentication_api_models.py
      - web/server/security/signal_handlers.py
      - web/server/database/setup.py
      - web/server/routes/views/authentication.py
      - tests/web/links/**
      - docs/modernisation/work/WP-0k.md
      - docs/modernisation/work/WP-0k-evidence/**
      - .claude/agent-memory/harmony-backend-engineer/**
branch: "mig/WP-0k-configured-links-exact-usernames"
requirements: []          # decision 0006 names no SEC row; INV-1 and INV-3 apply
contracts_consumed: [C-5]
contracts_changed: []
security_review: true
---

# WP-0k: Build outgoing links from the configured origin; match usernames exactly

Decision 0006, phase 0 section 0k. Branched from `mig/WP-0i-render-route-guards` (WP-0i introduced the configured-origin helper in `web/server/routes/views/page_renderer.py`), with `mig/integration` 1697a7a merged.

## Plan

Each unit starts with a failing test.

1. **Does nginx-proxy 1.11.6 forward the raw Host?** On a local copy of the WP-2c stack (`tests/contract/stack` at b6e49b8) with `nginxproxy/nginx-proxy:1.11.6-alpine` in front of `web` as in `docker-compose.yaml`, send `forgot_password` with `Host: attacker.invalid` and `Host: real.org:@attacker.invalid`, over HTTP and HTTPS, and read the link mailpit receives. Check: evidence file with the requests, the Host the app saw and the mailed link.
2. **Every mailed or returned link comes from `DEPLOYMENT_BASE_URL`.** One helper builds an absolute URL for an endpoint on the configured origin with `url_map.bind('')`, never the request Host or `SCRIPT_NAME`. Callers: reset link (`admin.py`), invite link (`invite.py`), access-granted email (`permission_api_models.py`), new-dashboard email (`dashboard_api_models.py`), and any other `_external=True` or Host-derived URL. Check: tests with a forged Host and `environ_overrides={'SCRIPT_NAME': ...}` fail on the base and pass here.
3. **`send_email` links to the dashboard's own page.** The caller's free-form `dashboardUrl` contributes only the locale and the `#h=` session hash, as for renders. Check: tests with hostile `dashboardUrl` values.
4. **Usernames match exactly, ignoring case.** JWT login, flask-user's `find_user_by_username` and `find_user_by_email`, registration, invitation and role assignment compare `lower(username)` for equality, never a pattern. The JWT identity is `user.username`. Check: the look-alike case (`john_doe` for `john.doe`) fails on the base and passes here; an existing mixed-case login still works.
5. **INV-3 table, human acceptance list, request to qa to flip the WP-2b pins, carried risks.**

## Contract changes

None planned. C-5 (the `accessKey` JWT) keeps its layout; only the value of `identity` becomes the stored `user.username` instead of the string the user typed.

## Requests

## Log

- 2026-10-05 backend-0k unit 1: nginx-proxy 1.11.6 does not forward the raw Host: `@` in Host is 400, unserved hosts 503, the upstream Host is the normalised `$host`; direct to gunicorn a forged Host or `SCRIPT_NAME` poisons the reset link. Check: `WP-0k-evidence/unit1-nginx-host/probe-before.md` (22 raw requests on the WP-2c stack plus nginx-proxy, links read from mailpit).
- 2026-10-05 backend-0k unit 2: reset, invite, access-granted and new-dashboard links built by `web/server/util/deployment_links.py` (WP-0i's `deployment_origin` moved there) from `DEPLOYMENT_BASE_URL` and the URL map; the access-granted email links the dashboard's slug, not its resource name (9076899). Multi-item `with` statements nested so the web image's Python 3.8 parses the formatted files (1740a02). Check: `uv run pytest tests/web/links` 35 failed on 35e9a2d, each for a request-derived host, scheme, port, script root or the `_` slug; 35 passed after; `uv run pytest tests/web` 272 passed, 1 xfailed; `uv run --locked mypy` clean; ruff check and format clean on the touched files; every `web/server` file parses on the image's Python 3.8.20; live, the same 22 requests as unit 1 mail every reset link on the configured origin (`probe-after-unit2.md`).

## Evidence

- **Unit 1, nginx-proxy and the Host header:** `WP-0k-evidence/unit1-nginx-host/README.md`, with the overlay, the probes and their output.
## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
