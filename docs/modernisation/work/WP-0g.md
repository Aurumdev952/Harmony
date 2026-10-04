---
wp: "0g"
title: "Browser-share report from nginx logs"
status: review
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

- [ ] human: run `uv run prod/browser_share/browser_share.py --deployment <code> <logs>` against one deployment's production nginx logs and fill in [decision 0002](../decisions/0002-browser-baseline-for-tailwind-v4.md): the measurement table, the pasted output and the decision. This is the phase 7 decision-log entry, and phase 7 must not start until it is filled. It does not block review of the script.

## Log

- 2026-10-04 infra-3 unit 1: claimed WP-0g and wrote the plan; check: `ownership.py who` reports infra for `prod/browser_share/**`, shared for `tests/infra/**` and the WP and decision files.
- 2026-10-04 infra-3 unit 2: log-line parser and engine-based user-agent classifier; check: `pytest tests/infra` 37 passed, `ruff check` and `ruff format --check` clean, `mypy --strict` no issues.
- 2026-10-04 infra-3 unit 3: 30-minute sessions per (client, user agent), `BrowserShare` report per deployment, CLI over plain, gzipped and stdin logs with a synthetic fixture; check: `pytest tests/infra` 49 passed, ruff and `mypy --strict` clean, `uv run prod/browser_share/browser_share.py` on the fixture (plain, gzipped, stdin) prints the expected 10 sessions and 40.0% below baseline.
- 2026-10-04 infra-3 unit 4: placeholder [decision 0002](../decisions/0002-browser-baseline-for-tailwind-v4.md) with run instructions and the fields to fill; check: relative links resolve. `task_gate.py WP-0g` refuses on status, the pending verdicts, and `docs/modernisation/SPEC.md` plus `scripts/agents/ownership.py`. Those two come from the lead's `mig/decisions-0001-ownership` merge and drop out of the diff once that branch is on `main` and this branch is rebased.

## Evidence

- **Tests.** `uv run --no-project -p 3.13 --with pytest==8.4.2 pytest -q tests/infra` gives `49 passed`. They cover:
  - every classifier branch and each baseline boundary: Chrome 110 and 111, Firefox 127 and 128, Safari 16.3 and 16.4, and iOS judged by its OS version;
  - the combined, nginx-proxy `vhost` and `docker compose logs` line shapes, plus timezone offsets;
  - 30-minute session splits and out-of-order rotated gzip files;
  - separate deployments;
  - no client address reaching the output.
- **Static checks.**
  - `uvx ruff@0.16.10 check --select E,F,I,UP,B,SIM prod/browser_share tests/infra` and `ruff format --check` are clean.
  - `MYPYPATH=prod/browser_share uvx --python 3.13 --with pytest==8.4.2 mypy@2.4.0 --config-file=/dev/null --strict --explicit-package-bases prod/browser_share/browser_share.py tests/infra/test_browser_share.py` finds no issues.
  - The repo's `mypy.ini` is bypassed because it loads the legacy `sqlmypy` plugin. WP-2f replaces it.
- **Runtime.**
  - `uv run prod/browser_share/browser_share.py tests/infra/testdata/zz/access.log` prints 10 sessions, Chrome 126 at 20.0%, and 40.0% below baseline ("above the 5% phase 7 gate").
  - A gzipped copy with `--json`, and stdin with `--deployment`, give the same result.
  - Stdin without `--deployment` exits 2 with a usage error.
- **Fixture privacy.** It uses only RFC 5737 and RFC 3849 documentation addresses, loopback and `*.example.org` hosts.
- **Not done.** There is no measurement on real logs, because the repo has none. See Requests.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 qa-0g: fixture gitignored so 6/49 tests fail on a clean checkout; 0-session run reports gate pass; unbounded int() on UA digits crashes; Edge iOS Version/ token misclassifies; 'bot' matches CUBOT; quadratic regex on long non-matching lines. Findings consolidated by the lead. |
| reviewer | pending | |
| security | n/a | |
