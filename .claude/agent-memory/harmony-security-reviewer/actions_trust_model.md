---
name: actions-trust-model
description: Harmony CI trust facts to apply when judging Actions findings (who can run what with which token, and why write-all existed)
metadata:
  type: project
---

- Zenysis/Harmony is a public repo. `integration.yml` runs on `pull_request` and executes PR-controlled code (pip/yarn install, lint configs). Fork PRs get a read-only token and no secrets. A finding that only lets the PR author run code or emit workflow commands crosses no boundary, so drop it under fp-check.
- `write-all` came from commit 199a059 (2024-09), when the restrictive repo-default token broke the ghcr push and `gh pr view`. The scopes actually needed are `packages: write` and `pull-requests: read`.
- `workflow_dispatch` runs the workflow file *from the dispatched ref*. A writer can therefore always publish any image tag, including the mutable `:latest` that compose defaults to (`${DOCKER_TAG:-latest}`) and `:main` (through a tag named `main`). In-workflow `if: github.ref == ...` guards cannot stop this. Deployment image integrity needs digest pins (SEC-9 / WP-0b) or rulesets, not workflow edits.

**Why:** these facts decided the WP-0f verdict (2026-10-04, approved) and will recur in WP-0b, 2f and 3b.

**How to apply:** set the attacker in each candidate Actions finding to fork PR author, compromised dependency, or writer. Rate it against the token the attacker actually gets.

Related: [[actions-review-tooling]]
