---
name: logging-traps
description: Traps in Harmony's log/ package found in WP-2g review - regex redaction cost on client text, Celery plain-text output, ZEN_PROD and DEBUG level facts
metadata:
  type: project
---

- **Redaction regexes run on client-controlled text** (paths, headers, bodies) in a gevent worker. A pattern that can start at any `\b` inside a long run and scan to the run's end is quadratic; `[\w-]*?KEY[\w-]*` was cubic (`'token-' * 1333` took 75 s). Reviewers time 4000 to 8000-byte inputs like `a-a-a`, `token-token-`, `////`. Keep the timed tests in `tests/infra/test_log_format.py` (`_HOSTILE`) and add a hostile case for every new pattern. `log/` must stay Python 3.8 compatible, so no possessive quantifiers or atomic groups.
- **Celery 5.4 writes plain text to stdout** outside logging: the banner (stopped by the global `-q`, which must come before `worker`) and, on SIGTERM, `worker: Warm shutdown (MainProcess)`, which no option stops.
- **`--loglevel` on the worker is ignored** once `log.celery_signals` connects `setup_logging`; `LOG_LEVEL` applies. The old production config logged `ZenysisLogger` at DEBUG, so the INFO default drops those lines.
- **nginx-proxy 1.11.6 passes a client `X-Request-ID` through** unchanged and sets none of its own.

**Why:** the reviewer and QA found each of these in WP-2g's first review round (2026-10-05).
**How to apply:** check these before changing `log/config.py`, the worker command or nginx logging. See [[infra-tooling-traps]].
