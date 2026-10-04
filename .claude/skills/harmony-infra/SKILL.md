---
name: harmony-infra
description: Harmony's infrastructure work, covering Docker images on Python 3.13 with uv and Node 24, Docker Compose overlays, nginx routing for the Flask to FastAPI strangler, GitHub Actions CI, secrets handling, structured logging and observability. Use when touching docker/, docker-compose*.yaml, Makefile, .github, ci/, prod/ (nginx, cron), log/, pyproject.toml or requirements files. Pair it with the docker-skills plugin skills and astral:uv.
---

# Harmony infrastructure

Load these first:
- `docker-skills:docker-project-foundations`, `docker-skills:docker-build-strategies`, `docker-skills:docker-compose-patterns`;
- `docker-skills:docker-destructive-guardrails`, before any command that removes containers, volumes or images;
- `astral:uv` and `astral:ruff`.

## Constraints

- **Small teams on modest hardware run this** (README "Cost of ownership"). Never add a long-running service without removing one (INV-7). Prefer one Compose project per host, driven by `Makefile` targets.
- **No published ports except nginx** in production overlays (SEC-1). Development ports bind to `127.0.0.1`.
- **No default or empty secrets** (SEC-3). Images read secrets from env or files at runtime. Nothing secret is baked into an image, a layer or CI logs. Never read `.env`; settings deny it.
- **Pin everything** (SEC-9): base images by tag and digest, GitHub Actions by commit SHA with the tag in a comment, downloaded binaries by checksum.

## Python images (uv)

From https://docs.astral.sh/uv/guides/integration/docker/:
- Base: `python:3.13-slim-bookworm`.
- Copy uv from a pinned `ghcr.io/astral-sh/uv:<version>` image.
- Set `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy` and `UV_NO_DEV=1`.
- Install dependencies first (`uv sync --locked --no-install-project`), then the project (`uv sync --locked --no-editable`), so the dependency layer caches.
- Build multi-stage. The runtime stage holds only `.venv` and the app, running as a non-root user.
- Add `.venv` to `.dockerignore`.
- One image serves web, worker and beat with different commands. The pipeline image is separate and stops copying `web/` (`docker/pipeline/Dockerfile:169-170`).

## Node

Node 24 LTS in the client build image, the dev image and CI (FE-11), and `pnpm` through corepack. Delete the Node 14 install in `docker/dev/Dockerfile`.

## nginx during the strangler (WP-5a to WP-5h)

- `/api/v3/`, `/auth/` and `/render/` proxy to uvicorn. Everything else goes to gunicorn (Flask) until WP-5h.
- Keep proxy timeouts per location: short for `/api/v3/query` (about 60s, matching the Druid `context.timeout`), long only for exports.
- `/static/build/` is served with `Cache-Control: public, max-age=31536000, immutable` (PERF-5).
- Add security headers: HSTS when TLS is on, `X-Content-Type-Options`, `Referrer-Policy`, and a CSP that allows only self plus the configured tile host.

## CI (GitHub Actions)

- **One workflow per concern:** lint, type check, unit, contract, e2e, build. Each sets `permissions:` to the minimum. There is no `write-all`.
- **Runners** are pinned to `ubuntu-24.04`.
- **Caches** cover uv and pnpm, keyed on the lockfile.
- **Untrusted input.** Never run untrusted PR code with secrets. Do not combine `pull_request_target` with a checkout of the PR head.
- **Generated-client drift** fails the build (C-4).
- **Delete `ci/docker/Jenkinsfile`** once the human confirms no deployment uses it (WP-0f).

## Logging and observability

- **Logs** are JSON lines on stdout with a `request_id`. The 512 KB rotating files in `log/config.py` go away (WP-2g).
- **Traces** are OpenTelemetry over OTLP to whatever collector the deployment runs. It is optional and off by default.
- **Metrics** are Prometheus `/metrics` on the API, scraped internally only.
- **Health checks** split liveness (`/api/v3/health/live`) from readiness (`/api/v3/health/ready`). Compose healthchecks call them. They are not TCP probes.

## Checks

```bash
docker compose -f docker-compose.yaml [overlays] config --quiet
docker build --check .
uv lock --check
actionlint
```

Also run `make up DEV=1` and the smoke suite. Confirm `docker compose ps` shows only nginx published in the production overlay.
