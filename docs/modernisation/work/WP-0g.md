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
- **Input.** nginx `combined` lines, matched by an anchored pattern so junk lines fail in linear time, and the `vhost` format that `nginxproxy/nginx-proxy` writes (`$host` prefix, `$upstream_addr` suffix). Lines may carry a `docker compose logs` prefix. Plain or gzipped files (detected by magic bytes), or `-` for stdin, so `docker logs <nginx>` can be piped straight in.
- **Deployment.** `--deployment` is required; one run covers one deployment.
- **Session.** No session id is logged, so a session is one (client address, user agent) pair with no gap longer than 30 minutes. Addresses are only held in memory as keys and never printed.
- **Exclusions.** Bots (`bot/`, `bot;`, `bot-` or the whole word, so device names such as CUBOT pass), crawlers, monitors, scripted clients and empty user agents are counted and excluded from shares.
- **Baseline.** Judged on the rendering engine, not the brand: Blink by its `Chrome/N` token (covers Edge, Opera, Samsung Internet, UC Browser), Gecko by `Firefox/N`, WebKit by `Version/x.y` on macOS and on iOS by the higher of the OS version and `Version/x.y` (every iOS browser is WebKit; Safari 26 freezes the OS token at 18_6 and Edge iOS truncates `Version/`). Version numbers are bounded to five digits. Trident and EdgeHTML are always below. Unknown engines are reported separately, not counted as below.
- **Gate.** Compares raw counts (`below * 100 > 5 * sessions`), rounding only for display. With zero sessions the gate is `not evaluated` and the script exits 1.

Units:
1. Claim the WP and write this plan. Check: `ownership.py who` on every planned path.
2. Log-line parser and user-agent classifier (`family`, `major`, engine, below-baseline) with unit tests. Check: pytest, ruff check, ruff format --check, mypy --strict.
3. Sessionising, per-deployment `BrowserShare` report, CLI (files, gzip, stdin, `--deployment`, `--json`) with a synthetic fixture and tests. Check: the same static checks plus `uv run prod/browser_share/browser_share.py` on the fixture, plain and gzipped.
4. Decision placeholder `docs/modernisation/decisions/0002-browser-baseline-for-tailwind-v4.md` and the request for the human to run it. Check: links resolve; `task_gate.py WP-0g` reports only the pending verdicts.
5. Fix the consolidated QA and reviewer findings (1 to 10). Check: the full evidence re-run from a clean detached clone of the branch tip.

## Contract changes

None.

## Requests

- [ ] human: run `docker logs <nginx> 2>/dev/null | uv run prod/browser_share/browser_share.py --deployment <code> -` on one deployment's production host and fill in [decision 0002](../decisions/0002-browser-baseline-for-tailwind-v4.md): the measurement table, the pasted output and the decision. This is the phase 7 decision-log entry, and phase 7 must not start until it is filled. It does not block review of the script.

## Log

- 2026-10-04 infra-3 unit 1: claimed WP-0g and wrote the plan; check: `ownership.py who` reports infra for `prod/browser_share/**`, shared for `tests/infra/**` and the WP and decision files.
- 2026-10-04 infra-3 unit 2: log-line parser and engine-based user-agent classifier; check: `pytest tests/infra` 37 passed, `ruff check` and `ruff format --check` clean, `mypy --strict` no issues.
- 2026-10-04 infra-3 unit 3: 30-minute sessions per (client, user agent), `BrowserShare` report per deployment, CLI over plain, gzipped and stdin logs with a synthetic fixture; check: `pytest tests/infra` 49 passed, ruff and `mypy --strict` clean, `uv run prod/browser_share/browser_share.py` on the fixture (plain, gzipped, stdin) prints the expected 10 sessions and 40.0% below baseline.
- 2026-10-04 infra-3 unit 4: placeholder [decision 0002](../decisions/0002-browser-baseline-for-tailwind-v4.md) with run instructions and the fields to fill; check: relative links resolve. `task_gate.py WP-0g` refuses on status, the pending verdicts, and `docs/modernisation/SPEC.md` plus `scripts/agents/ownership.py`. Those two come from the lead's `mig/decisions-0001-ownership` merge and drop out of the diff once that branch is on `main` and this branch is rebased.
- 2026-10-04 infra-3 unit 5: fixed review findings 1 to 10 (fixture committed as `access_log.txt`; gate on raw counts and `not evaluated` with exit 1 at zero sessions; bounded version digits; iOS takes the higher version; narrower bot pattern; anchored line regex; UC Browser; `--deployment` required; piped runbook and no notice promise in decision 0002), tests written first and seen failing; check: from a clean detached clone at `ac4518b`, `pytest tests/infra` 79 passed, ruff, ruff format and `mypy --strict` clean, and all CLI modes behave as listed under Evidence.

## Evidence

All of this was re-run on 2026-10-04 from a clean detached clone of the branch tip (`git clone` of the branch, `git checkout --detach ac4518b`, `git status --ignored` empty), not from the worktree.

- **Tests.** `uv run --no-project -p 3.13 --with pytest==8.4.2 pytest -q -p no:cacheprovider tests/infra` gives `79 passed in 0.44s`. They cover:
  - every classifier branch and each baseline boundary: Chrome 110 and 111, Firefox 127 and 128, Safari 16.3 and 16.4, iOS by OS version, Edge iOS on 16.4 and 16.5 with a truncated `Version/16.0`, and Safari 26 with the frozen `18_6` OS token;
  - UC Browser named as such, at its Blink version;
  - version numbers of 5,000 digits in Chrome, iOS and Firefox user agents, which classify as unknown without raising;
  - bots (Googlebot, Slackbot, `bot` as a word), and a CUBOT X30 phone that is not a bot;
  - the combined, nginx-proxy `vhost` and `docker compose logs` line shapes, timezone offsets, and JSON-format lines rejected;
  - six 50,000-character junk lines rejected in under 1 s in total (5 ms measured). The old unanchored pattern took 0.03 to 0.05 s at 4,000 characters on the no-space shapes, which grows quadratically;
  - the gate on raw counts: 500 of 10,000 is within, and 501 and 504 of 10,000 are above, while 504 displays as 5.0%;
  - zero sessions (empty input, only malformed lines, a single bot, an unrecognised format) giving `not evaluated`, and the CLI exiting 1 in text and JSON;
  - 30-minute session splits and out-of-order rotated gzip files;
  - stdin input, `--deployment` required, and no client address reaching the output.
- **Static checks.**
  - `uvx ruff@0.16.10 check --no-cache --select E,F,I,UP,B,SIM prod/browser_share tests/infra` passes, and `ruff format --no-cache --check` reports both files already formatted.
  - `MYPYPATH=prod/browser_share uvx --python 3.13 --with pytest==8.4.2 mypy@2.4.0 --config-file=/dev/null --cache-dir=/dev/null --strict --explicit-package-bases prod/browser_share/browser_share.py tests/infra/test_browser_share.py` finds no issues.
  - The repo's `mypy.ini` is bypassed because it loads the legacy `sqlmypy` plugin. WP-2f replaces it.
- **Runtime, from the clean clone.**
  - Plain file: `uv run prod/browser_share/browser_share.py --deployment zz tests/infra/testdata/zz/access_log.txt` prints 10 sessions, Chrome 126 at 20.0%, and "4 of 10 sessions, 40.0% (above the 5% phase 7 gate; phase 7 needs a fallback plan)". Exit 0.
  - Gzipped with `--json`: the same numbers, with `"phase_7_gate": "above"`. Exit 0.
  - Stdin (`--deployment zz -`): the same result. Exit 0.
  - Empty stdin: "Phase 7 gate not evaluated: no browser sessions found", exit 1; with `--json`, `"phase_7_gate": "not evaluated"`, exit 1.
  - No `--deployment`: a usage error, exit 2.
- **Fixture.** `tests/infra/testdata/zz/access_log.txt` is now committed (`*.log` is gitignored, so the old name never was). It uses only RFC 5737 and RFC 3849 documentation addresses, loopback and `*.example.org` hosts.
- **Not done.** There is no measurement on real logs, because the repo has none. See Requests.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | changes-requested | 2026-10-04 qa-0g: fixture gitignored so 6/49 tests fail on a clean checkout; 0-session run reports gate pass; unbounded int() on UA digits crashes; Edge iOS Version/ token misclassifies; 'bot' matches CUBOT; quadratic regex on long non-matching lines. Findings consolidated by the lead. |
| reviewer | changes-requested | 2026-10-04 rev-0g: fixture not committed (gitignored *.log); gate compares a rounded share (5.04% passes) and passes with 0 sessions; runbook copies raw access log to /tmp; bot pattern too broad; deployment inference from folder; UC Browser labelled Chrome. Consolidated findings sent to the builder. |
| security | n/a | |
