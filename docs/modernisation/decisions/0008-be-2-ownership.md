# 0008. BE-2 is owned by the settings consumers, not by WP-4a alone

Status: applied by the lead on 2026-10-05, pending human ratification (SPEC section 10).

## Context

WP-4a built `harmony.core.settings` and moved the reads it owns onto it, but the WP-4a review showed that many runtime reads of the environment live in web, worker, pipeline and launcher code that later WPs rewrite (Celery and Redis configuration, mail and SMS, Hasura secret, `ZEN_ENV` and `ZEN_PROD` flags, gunicorn and pipeline launchers). SPEC listed BE-2 against 3a and 4a only, so once WP-4a closed, the remaining reads would have had no owner.

## Decision

1. The BE-2 row in SPEC section 3 lists `3a, 4a, 4b, 4c, 4f, 5a` plus the pipeline WPs `8d, 8e`. WP-4a records BE-2 as partial with a table of every remaining read and its target WP; each target WP closes its rows and the last one (5a or 8e) marks BE-2 complete.
2. Launchers that only choose a process shape (gunicorn worker class and count, listen address, `SERVER_SOFTWARE`) may read the environment directly if the WP that owns them records why.

## Consequences

- SPEC 1.8: BE-2 row amended.
