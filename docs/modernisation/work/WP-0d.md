---
wp: "0d"
title: "Delete dead backend code and dependencies"
status: building
owner_role: "core"
instances:
  - name: "core-2"
    files:
      - docs/modernisation/work/WP-0d.md
branch: "mig/WP-0d-dead-backend-code"
requirements: []
contracts_consumed: []
contracts_changed: []
security_review: false
---

# WP-0d: Delete dead backend code and dependencies

Phase detail: [phase-0-security-and-subtraction.md, section 0d](../phase-0-security-and-subtraction.md).

## Ownership finding

Every path the phase file lists for 0d is owned by another role (`uv run python scripts/agents/ownership.py who ...`):

| Path | Owner |
|---|---|
| `requirements.txt`, `requirements-web.txt`, `requirements-pipeline.txt`, `requirements-dev.txt`, `mypy.ini`, `log/config.py` | infra |
| `web/server/routes/graphql_api.py`, `web/server/graphql/**`, `web/server/app.py`, `web/server/routes/api.py` | backend |
| `db/druid/indexing/resources/**`, `db/druid/indexing/legacy_task_builder.py`, `db/druid/indexing/scripts/run_indexing.py` | data-platform |
| `web/client/util/graphql/**` | frontend-platform |

No core-owned file (`config/`, `data/query/`, `db/` outside `db/druid/indexing/`, `models/`, `util/`, `web/server/{query,data,migrations}`) imports a removed package. Core's part of this WP is therefore to prove each deletion is dead, write the exact change for each owner, and verify the combined change builds and imports.

## Plan

1. Claim; record ownership. Check: ownership tool output above.
2. Prove each target is dead (grep for imports, string references, route callers). Check: grep transcripts under Evidence.
3. Write exact change requests per owning role. Check: each request lists files, lines and blocking unit.
4. Verify the combined change in a throwaway copy (never committed): the web-server image builds with the trimmed requirements; an import sweep over every backend module gives the same result with and without the removed packages installed, apart from the deleted modules; the trimmed pipeline requirements still resolve. Check: build and sweep output under Evidence.

## Contract changes

None.

## Requests

## Log

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | n/a | |
