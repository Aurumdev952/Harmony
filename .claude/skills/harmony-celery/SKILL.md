---
name: harmony-celery
description: Writing and migrating Harmony's Celery 5.6 tasks on Redis, including email and SMS, export rendering, alert evaluation and scheduled dashboard emails. Use when touching web/server/tasks, web/server/workers, harmony/worker, celery beat schedules, or any work moved out of a request. No official Celery skill exists; load redis-development:redis-core for broker-side Redis facts.
---

# Celery in Harmony

## Current state

- **Two tasks.** `send_email_task` and `send_sms_task` live in `web/server/tasks/notifications.py`.
- **The worker builds a Flask app** in `worker_process_init` (`web/server/workers/__init__.py:12-28`). WP-4f replaces that with `AppContext`.
- **No beat schedule.** `models/alchemy/schedule` (`SchedulerEntry`) has no consumer yet.

## Target

`harmony/worker/app.py` defines the Celery app. Tasks live by domain: `harmony/worker/tasks/{notifications,exports,alerts,imports}.py`. Each task:
- builds or reuses a process-level `AppContext` (`harmony.core.context`);
- **takes ids and plain values, never ORM objects or `Principal` instances.** Re-load what it needs inside the task, and re-check permissions there;
- is **idempotent**. The Redis broker can redeliver, so check state before acting. An export job that already has a file returns it;
- sets explicit `time_limit` and `soft_time_limit`;
- logs JSON with the job id and the originating request id.

## Configuration rules

- Use Celery 5.6 or later. It fixed plaintext logging of broker URLs that contain passwords. Never log the broker URL yourself.
- Use `task_acks_late=True` and `task_reject_on_worker_lost=True` for exports and alerts. With late acks, set the Redis `visibility_timeout` above the longest task's hard limit. Otherwise a long task is redelivered while it still runs. Verify the current default in the Celery docs for the installed version before relying on it.
- Run Beat as its own process (`celery beat`), not `worker --beat`, which `docker-compose.yaml` uses today. Exactly one beat process may run per deployment.
- Separate queues: `default`, `exports` (Playwright, memory-heavy, concurrency 1 or 2), and `alerts`.
- Redis requires a password (SPEC SEC-1, SEC-3). The URL comes from settings, never from code.

## Moving work out of requests

- **Routes enqueue and return immediately.** The route enqueues with `apply_async` and returns `202 {job_id}`. Progress is read from a `RenderJob` or `ImportJob` row, not from the Celery result backend.
- **Tests run tasks eagerly** with `task_always_eager=True` in a dedicated fixture. Never use eager mode in production code paths. Today `NotificationService` switches between `apply` and `apply_async` by environment (`web/server/notifications/notification_service.py:16`). Remove that branch.

## Checks

```bash
uv run pytest harmony/worker tests -k celery
docker compose exec worker celery -A harmony.worker.app inspect ping
```
