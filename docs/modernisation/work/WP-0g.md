---
wp: "0g"
title: "Browser-share report from nginx logs"
status: building
owner_role: "infra"
instances:
  - name: "infra-3"
    files:
      - "prod/browser_share/**"
      - "tests/infra/test_browser_share.py"
      - "tests/infra/testdata/**"
      - "docs/modernisation/work/WP-0g.md"
      - "docs/modernisation/decisions/0002-browser-baseline-for-tailwind-v4.md"
branch: "mig/WP-0g-browser-share-report"
requirements: []
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-0g: Browser-share report from nginx logs

Phase detail: [phase-0-security-and-subtraction.md, section 0g](../phase-0-security-and-subtraction.md).

## Plan

The script lives in `prod/browser_share/` (infra-owned; `scripts/` outside `scripts/druid`, `scripts/db` and `scripts/perf` belongs to the lead). It is a PEP 723 script on Python 3.13 with no third-party dependencies, so there is nothing to pin or lock. Its unit tests and synthetic fixture live in `tests/infra/` (shared since decision 0001).

Design choices:
- **Input.** nginx `combined` lines and the `vhost` format that `nginxproxy/nginx-proxy` writes (`$host` prefix, `$upstream_addr` suffix). Lines may carry a `docker compose logs` prefix. Plain or gzipped files (detected by magic bytes), or `-` for stdin, so `docker logs <nginx>` can be piped straight in.
- **Deployment.** `--deployment` wins; otherwise the name of the file's parent directory.
- **Session.** No session id is logged, so a session is one (client address, user agent) pair with no gap longer than 30 minutes. Addresses are only held in memory as keys and never printed.
- **Exclusions.** Bots, crawlers, monitors, scripted clients and empty user agents are counted and excluded from shares.
- **Baseline.** Judged on the rendering engine, not the brand: Blink by its `Chrome/N` token (covers Edge, Opera, Samsung Internet), Gecko by `Firefox/N`, WebKit by `Version/x.y` on macOS and by the OS version on iOS (every iOS browser is WebKit). Trident and EdgeHTML are always below. Unknown engines are reported separately, not counted as below.

Units:
1. Claim the WP and write this plan. Check: `ownership.py who` on every planned path.
2. Log-line parser and user-agent classifier (`family`, `major`, engine, below-baseline) with unit tests. Check: pytest, ruff check, ruff format --check, mypy --strict.
3. Sessionising, per-deployment `BrowserShare` report, CLI (files, gzip, stdin, `--deployment`, `--json`) with a synthetic fixture and tests. Check: the same static checks plus `uv run prod/browser_share/browser_share.py` on the fixture, plain and gzipped.
4. Decision placeholder `docs/modernisation/decisions/0002-browser-baseline-for-tailwind-v4.md` and the request for the human to run it. Check: links resolve; `task_gate.py WP-0g` reports only the pending verdicts.

## Contract changes

None.

## Requests

## Log

- 2026-10-04 infra-3 unit 1: claimed WP-0g and wrote the plan; check: `ownership.py who` reports infra for `prod/browser_share/**`, shared for `tests/infra/**` and the WP and decision files.
- 2026-10-04 infra-3 unit 2: log-line parser and engine-based user-agent classifier; check: `pytest tests/infra` 37 passed, `ruff check` and `ruff format --check` clean, `mypy --strict` no issues.
- 2026-10-04 infra-3 unit 3: 30-minute sessions per (client, user agent), `BrowserShare` report per deployment, CLI over plain, gzipped and stdin logs with a synthetic fixture; check: `pytest tests/infra` 49 passed, ruff and `mypy --strict` clean, `uv run prod/browser_share/browser_share.py` on the fixture (plain, gzipped, stdin) prints the expected 10 sessions and 40.0% below baseline.

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
