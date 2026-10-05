# Harmony modernisation specification

Version 1.5, 2026-10-05 (decisions 0001, 0003, 0004, 0005). Status: approved for execution.

This is the binding guide for every agent and engineer working on the Harmony migration. Where this spec and another document disagree, this spec wins. The other documents explain why and describe the work in detail:

| Document | Use it for |
|---|---|
| [overview.md](overview.md) | Context, alternatives considered, phase order |
| [01-current-state.md](01-current-state.md) | What exists today, with file pointers |
| [02-architecture-deep-dive.md](02-architecture-deep-dive.md) | Performance evidence and known bugs |
| [03-target-architecture.md](03-target-architecture.md) | The end state in detail |
| [04-technology-research.md](04-technology-research.md) | Versions, constraints and sources |
| [05-ui-surface-inventory.md](05-ui-surface-inventory.md) | Every screen and `ui/` module, mapped to HeroUI |
| `phase-*.md` | The units of work behind each work package |
| [testing.md](testing.md) | Test suites and exit criteria |
| [TEAM.md](TEAM.md) | Agents, the skills each one loads, and how to run the team |

Requirement keywords: **MUST** and **MUST NOT** are absolute. **SHOULD** needs a written reason in the work-package file to deviate.

## 1. Outcome

When the migration is done, Harmony:

- serves one FastAPI backend on Python 3.13, built on a framework-free `harmony.core` package;
- serves one React 19 TypeScript single-page app, built with Vite 8 and styled with HeroUI v3, Tailwind CSS v4 and the Urbanist typeface, which works offline for recently viewed dashboards;
- queries Druid 37 or 38 on Java 21, loaded from a Polars pipeline that Dagster orchestrates and that reindexes only the months that changed;
- runs without Flask, Flask-Potion, Flask-User, Flask-Principal, Hasura, Relay, webpack, Flow, jQuery, bluebird, moment, Bootstrap, SCSS, PyPy, Zeus, py77 and urlbox;
- carries automated tests for every requirement below, run in CI on every pull request.

## 2. Invariants

These hold at every commit on `main`. A change that breaks one MUST NOT merge.

- **INV-1.** Every deployment under `config/<code>/` and `pipeline/<code>/` builds, starts and serves every page that existed before the change.
- **INV-2.** Query results are identical to before, unless a work package records the difference and a reviewer accepts it. The golden suite (`tests/golden/`) is the judge.
- **INV-3.** Authorisation decisions are identical to before, unless a security-reviewed work package changes them on purpose. The policy suite (`tests/authz/`) is the judge.
- **INV-4.** Stored dashboards, saved queries and alert definitions load and render. Readers for `$ref` URIs stay until WP-5g finishes.
- **INV-5.** Translations (`I18N.text`, the French, Portuguese and Amharic locales) and the Ethiopian calendar keep working.
- **INV-6.** No secret, credential, token or production data enters the repository, logs, test fixtures or agent transcripts.
- **INV-7.** The stack never gains a long-running service without losing one. Dagster's daemon replaces host cron.
- **INV-8.** CI is green on `main`.

## 3. Requirements

Each requirement names the work packages (WP, section 5) that satisfy it.

### Security

| ID | Requirement | WP |
|---|---|---|
| SEC-1 | No service other than nginx MUST publish a host port in production Compose files. | 0a, 0b |
| SEC-2 | Hasura MUST require an admin secret until WP-5e removes it. Requests MUST carry a role derived from the signed-in user. | 0a |
| SEC-3 | Every process MUST refuse to start with an empty or default secret. Session-signing and JWT keys MUST differ. | 0b |
| SEC-4 | Every query path, including raw and internal ones, MUST apply the caller's query policy, or be callable only from service code with no user input. | 0c, 4e |
| SEC-5 | Cookies carrying auth tokens MUST be `HttpOnly`, `Secure` in production and `SameSite=Lax`. Unsafe methods MUST pass CSRF protection. | 5d |
| SEC-6 | Reset, invite and confirmation tokens MUST be single-use, time-limited and stored hashed. | 5d |
| SEC-7 | Export rendering MUST use a token scoped to the one resource being rendered. | 1h |
| SEC-8 | Druid MUST run with JavaScript disabled. | 8a |
| SEC-9 | Images, downloads and dependencies MUST be pinned by version, and where possible by digest or checksum. | 0b, 2f |
| SEC-10 | Dashboard content MUST NOT be sent to third-party services by default. | 1h, 7g |

### Performance

| ID | Requirement | WP |
|---|---|---|
| PERF-1 | Query results MUST be cached server-side, keyed on `(datasource_version, request_hash, policy_hash)`. | 1b |
| PERF-2 | Every Druid call MUST carry both a client timeout and `context.timeout`. | 1d, 4c |
| PERF-3 | Post-processing MUST work on columns, not on one Python dict per row. | 1c |
| PERF-4 | Independent Druid sub-queries within one request MUST run concurrently. | 1f, 5b |
| PERF-5 | Static assets MUST have content-hashed names and be served `immutable`. | 1g, 6b |
| PERF-6 | Page renders MUST NOT call Druid. | 1d |
| PERF-7 | No phase may raise p95 latency on the baseline cases (`scripts/perf/`) by more than 10%. | all |
| PERF-8 | Pipeline runs MUST reindex only the months whose inputs changed. | 8c |

### Backend

| ID | Requirement | WP |
|---|---|---|
| BE-1 | `harmony/core` MUST NOT import `flask`, `fastapi` or `starlette`. An import-linter contract enforces this. | 4a-4f |
| BE-2 | All runtime configuration MUST load through `harmony.core.settings` (pydantic-settings). Deployment modules MUST NOT perform I/O when imported. | 3a, 4a |
| BE-3 | Database access MUST go through `harmony.core.db`, using the SQLAlchemy 2 `select()` style. Sessions are synchronous. | 3c, 3e, 4b |
| BE-4 | Every HTTP route MUST live under `harmony/api/` and be declared with typed Pydantic request and response models. | 5a-5h |
| BE-5 | New endpoints MUST live under `/api/v3/`. Errors MUST use the `ApiError` envelope (C-10). | 5a |
| BE-6 | Handlers that call Druid MUST be `async`. CPU-bound shaping MUST run in a worker thread. | 5b |
| BE-7 | Background work MUST run in Celery tasks that build their own `AppContext`, never a web app. | 4f |
| BE-8 | Logs MUST be JSON lines on stdout, each with a request id. Traces MUST use OpenTelemetry. | 2g, 5a |

### Frontend

| ID | Requirement | WP |
|---|---|---|
| FE-1 | Builds MUST use Vite 8. The production manifest is the only source of asset URLs. | 6b |
| FE-2 | New and converted code MUST be TypeScript 6 with `strict` on. New Flow files MUST NOT be added. TypeScript 7 (the native `tsgo` binary) MAY run as an extra fast type check, but typescript-eslint needs the TypeScript 6 API, so `typescript` stays on 6. | 6e |
| FE-3 | Server state MUST go through TanStack Query hooks generated from OpenAPI. Hand-written fetch calls to `/api/v3` are not allowed. | 5a-5h |
| FE-4 | The UI MUST use React 19 with `createRoot`. Decorators MUST NOT be used. | 6c |
| FE-5 | Every colour, font, radius, spacing and shadow MUST come from `web/client/design/tokens.css`. Hex literals elsewhere fail lint. | 7b |
| FE-6 | UI components MUST be HeroUI v3 or React Aria, unless [05-ui-surface-inventory.md](05-ui-surface-inventory.md) marks the component "keep custom". | 7c-7e |
| FE-7 | Text MUST use `--font-sans` (Urbanist stack). Numbers in tables, KPIs, axes and tooltips MUST use `--font-numeric` with tabular figures. | 7a, 7b |
| FE-8 | Every screen MUST pass axe with no serious or critical violations, and MUST work at 390, 1024 and 1440 pixel widths. | 7c-7e |
| FE-9 | Existing URLs MUST keep resolving after the move to a single-page app. | 7f |
| FE-10 | Charts MUST use visx 4 or later, or `d3-*` modules from npm. Maps MUST use MapLibre GL JS 6 through `@vis.gl/react-maplibre`. | 7g |
| FE-11 | Node MUST be 24 LTS in every image and in CI. Lint MUST be ESLint 10 flat config. | 6b, 6e |
| FE-12 | Function components MUST NOT rely on `defaultProps` or `propTypes`, which React 19 ignores. Use default parameter values. | 6c |

### Data platform and pipeline

| ID | Requirement | WP |
|---|---|---|
| DATA-1 | Query builders MUST give correct results under SQL-compatible null handling. | 8a |
| DATA-2 | Druid MUST run a supported release on Java 21. | 8b |
| DATA-3 | Ingestion MUST read Parquet through SQL-based `REPLACE ... OVERWRITE WHERE` per month. Each deployment MUST have one stable datasource name. | 8c |
| DATA-4 | Pipeline transforms MUST be Polars expressions. Row-level Python hooks are allowed only through `map_elements` and MUST log a warning. | 8d |
| DATA-5 | Pipeline orchestration MUST be Dagster assets. A failed run MUST stop and alert. It MUST NOT swallow errors. | 8e |
| DATA-6 | A switch to ClickHouse happens only through WP-8f's written decision. | 8f |

### Quality

| ID | Requirement | WP |
|---|---|---|
| QA-1 | Every bug fix MUST land with a test that failed before the fix. | all |
| QA-2 | Every endpoint moved to FastAPI MUST pass the contract cases recorded against Flask. | 2c, 5* |
| QA-3 | Every user-visible change MUST be checked in a running app with the `verify` skill, and the evidence linked from the work-package file. | all UI |
| QA-4 | Every work package MUST meet its phase exit check in [testing.md](testing.md) before it closes. | all |

## 4. Contracts

A contract is an interface that more than one agent depends on. Only its owner changes it, following the protocol in section 7.4.

| ID | Contract | Location | Owner |
|---|---|---|---|
| C-1 | `AppContext` | `harmony/core/context.py` | core |
| C-2 | `Principal` and `can()` | `harmony/core/authz/` | core |
| C-3 | `QueryRequest` / `QueryResponse` and their JSON Schema | `harmony/core/query/models.py` | core |
| C-4 | OpenAPI document and the generated TypeScript client | `harmony/api/openapi.json`, `web/client/api/generated/` | backend |
| C-5 | Session and JWT format (`accessKey` cookie and claims) | `harmony/core/authz/tokens.py` | backend |
| C-6 | Design tokens | `web/client/design/tokens.css` | frontend-design |
| C-7 | Vite manifest helper and page bootstrap (`/api/v3/session/bootstrap`) | `harmony/api/pages.py` | frontend-platform with backend |
| C-8 | Parquet ingest schema and datasource naming | `harmony/core/druid/schema.py` | data-platform |
| C-9 | Result-cache key | `harmony/core/cache.py` | core |
| C-10 | `ApiError` envelope | `harmony/api/errors.py` | backend |
| C-11 | Legacy `$ref` reader (`parse_legacy_ref`), removed in WP-5g | `harmony/core/refs.py` | core |

## 5. Work packages

Each WP is one pull request, or a short stack of them. Detail lives in the named phase file. The owner is an agent role from [TEAM.md](TEAM.md). `Sec` marks WPs that need sign-off from `harmony-security-reviewer`.

| WP | Title | Owner | Supporting | Depends on | Sec |
|---|---|---|---|---|---|
| 0a | Lock down Hasura | backend | infra | none | yes |
| 0b | Close published ports, refuse default secrets, pin images | infra | none | none | yes |
| 0c | Fix the pure-mistake bugs | backend | core, infra | none | yes |
| 0d | Delete dead backend code and dependencies | core | backend | none | no |
| 0e | Delete dead frontend code and dependencies | frontend-platform | none | none | no |
| 0f | One CI system, `main` branch, least-privilege Actions | infra | none | none | yes |
| 0g | Browser-share report from nginx logs | infra | qa | none | no |
| 0h | Close privilege escalations in group and role management | backend | core, security, qa | 2b | yes |
| 0i | Guard the dashboard render and thumbnail routes | backend | security, qa | none | yes |
| 0j | Refuse username changes and password resets that reach a higher-privileged account | backend | security, qa | 0h | yes |
| 1a | Performance baseline | qa | core | none | no |
| 1b | Shared result cache | core | none | 1a | yes |
| 1c | Columnar parsing | core | none | 1a, golden cases | no |
| 1d | Timeouts, no prod reload, request-scoped datasource, no Druid on render | core | infra | 1a | no |
| 1e | Real table streaming, outliers fix | core | none | 1a | no |
| 1f | Concurrent sub-queries | core | none | 1a | no |
| 1g | Front-end payload hygiene | frontend-platform | infra | 1a | no |
| 1h | Self-hosted export renderer | backend | infra, qa | none | yes |
| 2a | Golden query suite | qa | core | none | no |
| 2b | Permission and policy suite | qa | core, security | none | yes |
| 2c | API contract recordings | qa | backend | none | no |
| 2d | Pipeline fixture suite | qa | pipeline | none | no |
| 2e | Frontend unit and end-to-end harness | qa | frontend-platform | none | no |
| 2f | uv, ruff, mypy, CI running every suite | infra | qa | 0f | yes |
| 2g | Structured logging | infra | backend | none | no |
| 3a | Config import hook on `find_spec` | core | none | 2a | no |
| 3b | One CPython 3.13 interpreter everywhere | infra | pipeline | 3a, 2f | no |
| 3c | SQLAlchemy 1.4 with 2.0 warnings | core | none | 2a, 2b | no |
| 3d | Flask 2.3, jwt-extended 4, PyJWT 2 | backend | none | 2c | yes |
| 3e | SQLAlchemy 2.1 | core | none | 3c | no |
| 3f | Replace py77 | core | pipeline | 3b | no |
| 4a | Settings and deployment loading | core | none | 3a | no |
| 4b | `harmony.core.db` | core | none | 3e | no |
| 4c | Druid client and datasource registry | core | data-platform | 4a | no |
| 4d | Query engine into the core | core | none | 4c | no |
| 4e | Authorisation as pure functions | core | security | 4b | yes |
| 4f | `AppContext`; Celery without Flask | core | backend | 4a-4e | no |
| 5a | FastAPI skeleton, auth dependency, nginx routing, codegen | backend | infra, frontend-platform | 4f | yes |
| 5b | Query and data-quality routers | backend | core, frontend-platform | 5a | no |
| 5c | Read-only metadata routers | backend | frontend-platform | 5a | no |
| 5d | Identity: auth flows, users, groups, roles, policies, OIDC | backend | frontend-platform, security | 5a, 4e | yes |
| 5e | Catalog routers; retire Hasura and Relay | backend | frontend-platform | 5a | yes |
| 5f | Dashboards, sharing, alerts, configuration, exports | backend | frontend-platform | 5a, 1h | yes |
| 5g | Rewrite stored `$ref` URIs | core | backend, qa | 5b-5f | yes |
| 5h | Pages on FastAPI; delete Flask | backend | infra, frontend-platform | 5b-5g | yes |
| 6a | `fetch` instead of jQuery and bluebird | frontend-platform | none | 2e | no |
| 6b | Vite 8 and the manifest helper | frontend-platform | backend | 6a | no |
| 6c | React 19, decorators removed | frontend-platform | none | 6b | no |
| 6d | Vitest and Storybook | frontend-platform | qa | 6b | no |
| 6e | Flow to TypeScript, directory by directory | frontend-platform | frontend-design, visualization | 6c | no |
| 6f | Runtime-loaded vendor scripts become npm imports | frontend-platform | visualization | 6b | yes |
| 7a | Typography prototype and surface report | frontend-design | qa | 6c | no |
| 7b | Tokens, fonts, theme | frontend-design | visualization | 7a | no |
| 7c | Shell, auth pages, error pages, Overview | frontend-design | frontend-platform | 7b | no |
| 7d | Primitives behind their existing APIs | frontend-design | none | 7b | no |
| 7e | Page waves 1 to 4 | frontend-design | frontend-platform, visualization | 7d | no |
| 7f | Single-page shell and PWA | frontend-platform | frontend-design, backend | 7c, 5h | no |
| 7g | Charts and maps on visx and MapLibre | visualization | frontend-design | 7b | yes |
| 7h | Delete SCSS and Bootstrap; dark mode | frontend-design | none | 7e, 7g | no |
| 8a | Remove Druid JavaScript; null-handling audit | data-platform | core | 2a | yes |
| 8b | Druid 37/38 on Java 21 | data-platform | infra | 8a | yes |
| 8c | Parquet and per-month SQL ingestion | data-platform | pipeline | 8b | no |
| 8d | Columnar pipeline (Polars) | pipeline | none | 2d, 3b | no |
| 8e | Dagster instead of cron and Zeus | pipeline | infra, backend | 8d | no |
| 8f | Warehouse decision gate (ClickHouse) | data-platform | core, qa | 8b | no |

Several streams run in parallel. Phases 0, 1 and 2 have no dependencies on each other. After WP-4f, the backend, frontend and data streams proceed independently. Inside one WP, several instances of the same agent role may work at once, provided each claims separate files (section 7.2).

## 6. Ownership of paths

Only the owning role edits a path. Other roles change it by request (section 7.3).

**How a path's owner is decided.**
- The table below is machine-read by `scripts/agents/ownership.py`, which enforces it as an edit hook and in the completion gate. Keep the format: a role name, then backticked globs.
- When several globs match a path, the one with the **longest literal prefix** wins. `web/server/query/x.py` belongs to core, not backend.
- Paths matched by the `shared` row are editable by every role.
- Paths that match no row belong to the human lead. That covers `.claude/**`, `CLAUDE.md`, `scripts/agents/**` and the planning documents in `docs/modernisation/*.md`.

<!-- ownership:start -->
| Role | Globs |
|---|---|
| core | `harmony/core/**`, `config/**`, `data/query/**`, `db/**`, `models/**`, `util/**`, `web/server/query/**`, `web/server/data/**`, `web/server/migrations/**` |
| backend | `harmony/api/**`, `harmony/worker/**`, `web/server/**`, `web/python_client/**`, `web/*.py`, `graphql/**`, `scripts/db/**` |
| frontend-platform | `web/client/**`, `web/public/js/**`, `web/webpack*.js`, `lint/**`, `vite.config.ts`, `tsconfig*.json`, `eslint.config.js`, `.eslintrc`, `.eslintignore`, `.flowconfig`, `.prettierrc`, `relay.config.js`, `jsconfig.json` |
| frontend-design | `web/client/design/**`, `web/client/components/**`, `web/public/scss/**`, `web/public/fonts/**`, `web/public/images/**`, `web/server/templates/emails/**`, `.stylelintrc` |
| visualization | `web/client/components/visualizations/**`, `web/client/components/ui/visualizations/**`, `web/client/components/QueryResult/**` |
| data-platform | `druid_setup/**`, `db/druid/indexing/**`, `scripts/druid/**`, `harmony/core/druid/schema.py` |
| pipeline | `pipeline/**`, `data/pipeline/**`, `data/alerts/**`, `util/pipeline/**`, `harmony/pipeline/**` |
| infra | `docker/**`, `docker-compose*.yaml`, `Makefile`, `.github/**`, `ci/**`, `prod/**`, `log/**`, `requirements*.txt`, `.env.example`, `.dockerignore`, `mypy.ini`, `.pylintrc` |
| qa | `tests/golden/**`, `tests/authz/**`, `tests/contract/**`, `tests/pipeline/**`, `tests/conftest.py`, `e2e/**`, `scripts/perf/**`, `playwright.config.ts`, `vitest.config.ts`, `vitest.workspace.ts` |
| shared | `tests/**`, `docs/modernisation/work/**`, `docs/modernisation/decisions/**`, `docs/modernisation/perf/**`, `.claude/agent-memory/**`, `scripts/codemods/**`, `pyproject.toml`, `uv.lock`, `package.json`, `pnpm-lock.yaml`, `yarn.lock` |
<!-- ownership:end -->

Rules that apply across these boundaries:
- **Reviewer and security roles** edit only `shared` paths: their verdicts and decision drafts. They never edit production code.
- **Shared manifests.** Any role MAY add or bump a dependency in `pyproject.toml` or `package.json` inside its own WP branch. Lockfiles are always regenerated (`uv lock`, `pnpm install`), never merged by hand.
- **Unit tests stay with the code.** Builders write unit tests next to the code they own. QA owns the cross-cutting suites.

## 7. Collaboration protocol

### 7.1 Work-package lifecycle

1. **Claim.** Create `docs/modernisation/work/WP-<id>.md` from [work/_template.md](work/_template.md), with status `claimed`, your role and an instance name (for example `core-1`). If the file already exists with another owner, pick another WP. Under agent teams, also claim the matching task in the shared task list.
2. **Plan.** Fill in the plan section: units, files you will touch, contracts you consume or change, tests you will add. Run `pstack:how` on any subsystem you have not read in this session.
3. **Branch.** Work in an isolated git worktree on branch `mig/WP-<id>-<slug>`. Never commit to `main`.
4. **Build in units.** Each unit is one change that ends in a check (section 8). Commit after each green unit. Append one line per unit to the log section of the WP file.
5. **Self-verify.** Run the static checks and the runtime checks for your surface, and link the evidence.
6. **Request review.** Set status to `review`. The QA, reviewer and, if Sec is yes, security roles review in parallel. Each writes its verdict into the WP file.
7. **Fix and re-request** until every verdict is `approved`.
8. **Open the pull request.** Set status to `ready`. A human merges. Agents MUST NOT merge to `main`, force-push shared branches, deploy, or run data migrations against anything but local copies.

### 7.2 Several agents in one area

- Split a WP into sub-claims in its file: `files:` lists per instance. Two instances MUST NOT claim the same file.
- Rebase on `main` before each unit. When a rebase touches files claimed by another instance, message that instance before resolving.
- Shared state is separated before it is shared. Every agent writes only its own WP file, its own branch and its own claimed files.

### 7.3 Asking another role for a change

- **Under agent teams:** message the owning teammate and add a task to the shared list with `blocked-by`.
- **Without teams:** add an entry to the `Requests` section of your WP file, naming the owning role, and stop work on the blocked unit. The lead routes it.
- The owning role either makes the change in its own WP, or answers with a reason and an alternative.

### 7.4 Changing a contract

1. The owner writes a contract-change note in its WP file: the old shape, the new shape, every consumer, and the migration.
2. Every consuming role acknowledges in the same file before the change merges.
3. Producer and consumers land in the same stack. Contracts are never left half-migrated (migrate callers, then delete).

### 7.5 Stop and escalate

Stop and write `status: blocked` with a question for the human when:
- a requirement or invariant conflicts with the work;
- a change needs a secret, production data or a production system;
- an irreversible action is needed (merge, deploy, data migration on real data, deleting a deployment's data);
- two roles disagree after one exchange of messages.

## 8. Definition of done for a unit and a work package

A **unit** is done when:
- the change is one logical step;
- lint, type check and the unit tests for the touched area pass;
- the runtime check for the surface passed (`verify` for UI, `run` for CLI and pipeline, contract replay for API);
- `/deslop` has run over the diff and no narrating comments remain.

A **work package** is done when:
- every unit is done;
- the requirements it names are met and demonstrated in the WP file;
- the phase exit check in [testing.md](testing.md) passes;
- the QA, reviewer and, where marked, security verdicts are `approved`;
- the pull request description lists the requirement IDs, the evidence, and anything deliberately deferred.

## 9. Standards per stack

The skills listed in [TEAM.md](TEAM.md) hold the details. These rules override any skill.

- **Python:** 3.13; uv for every install and run; ruff for formatting and lint; mypy strict on `harmony/**`; types at boundaries, Pydantic at I/O edges, plain dataclasses inside.
- **TypeScript:** `strict`; no `any` except at generated boundaries; named exports; one component per file; hooks over classes in new code.
- **SQL and Druid:** native expressions only; queries built through the core builder, never as string concatenation of user input.
- **Comments:** only a non-obvious *why*. No narration, no commented-out code.
- **Commits:** imperative subject line naming the WP, for example `WP-1b: cache query results keyed on datasource version`.

## 10. Decision log

Decisions that change this spec are recorded in `docs/modernisation/decisions/NNNN-slug.md` (context, options, decision, consequences) and approved by a human before this file is edited. Bump the version line at the top when this file changes.
