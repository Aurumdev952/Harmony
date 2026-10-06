# WP-1h unit 4a: egress, SSRF and sandbox (security review follow-up)

Date: 2026-10-04. The threat model is in `../WP-1h.md`, section "Renderer threat model".

## Red first (code from b1cf27d, new tests)

Run in the image with `--network none`:

- `test_every_other_destination_is_blocked_and_recorded` failed. The second origin received `GET /socket` with `Cookie: accessKey=<token>`: a WebSocket to another port on the same host carried the token. Playwright's request route does not see WebSockets, and a cookie is scoped to a host, not a port.
- `test_a_redirect_to_another_origin_fails_and_never_reaches_it` failed with a raw `playwright Error` instead of `PageFailed`.
- `test_render_refuses_a_spec_off_the_allowed_origin_without_a_browser` failed in 4 cases: `browser.render` trusted its spec.
- `test_chromium_runs_with_its_sandbox` failed: the Chromium processes had `--no-sandbox`, which is Playwright's default.

The spec and egress cases (userinfo tricks, `169.254.169.254`, IPv6 literals, hex IP, `wss:`, `ftp:`) already passed. The parser and `is_allowed` compare parsed origins exactly.

## Green

```
docker run --rm --network none \
  --security-opt seccomp=docs/modernisation/work/WP-1h-evidence/infra-request/seccomp_profile.json \
  -v <worktree>:/src:ro harmony-renderer-test:wp1h tests/worker/renderer -q
110 passed in 33.21s
```

All 17 browser tests pass, including:
- the proxy fence alone, with the request route patched to allow everything: the second origin gets zero TCP connections;
- the sandbox check: no Chromium process has `--no-sandbox` or `--no-zygote`.

The same sandbox test without `--security-opt seccomp=...` (Docker's default profile) fails: `BrowserType.launch: Target page, context or browser has been closed`. Chromium refuses to start without its sandbox, and the renderer never falls back.

`seccomp_profile.json` is Playwright's profile at tag v1.63.0, `utils/docker/seccomp_profile.json`, sha256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.

Host: `uv run pytest tests/worker tests/web` gives 289 passed, 1 skipped (browser) and 1 failed. The failure is the existing `flask_migrate` import.

Static checks: black, ruff (`F,E9,B,UP,I`) and mypy (3.12, playwright 1.63.0) are clean.
