---
name: celery-startup-checks
description: Startup refusals inside Celery worker_process_init are swallowed (worker reports ready); put them at import of the -A module
metadata:
  type: project
---

An exception in a `worker_process_init` handler (`web/server/workers/__init__.py`, which builds the Flask app per pool child) is logged per child, and the worker still reports ready and passes `celery status`. QA caught this in WP-0b (2026-10-04): a worker started with `JWT_SECRET_KEY=changeme`. Since then `web/background_worker.py` checks the keys at import, so `celery -A web.background_worker.celery` exits 2 with "Unable to load celery application" before the pool starts.

**Why:** a refusal that only logs is not a refusal. Compose health checks see a running worker.

**How to apply:** For `harmony/worker/app.py` (WP-4f), put settings and secret validation at module import of the Celery app, and test it by importing the module in a fresh interpreter, not by calling the init hook. Related: [[jwt-key-rotation]].
