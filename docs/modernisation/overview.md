# Harmony modernisation plan

Status: proposal, 2026-10-04. Nothing in this directory has been implemented yet.

## Context

Harmony is meant to let a ministry of health integrate messy health data and answer questions over it in under a second. It is meant to do that at a cost a two-person government tech team can carry. The codebase still does the job, but it has stopped moving. Every runtime it ships on is past end of life:
- Python 3.8 and 3.9
- Node 14 and 18
- Hasura v2.11 (retired 2024-09-01)
- Druid 0.23
- Flask 1.0.1

There are no automated tests, and two security exposures are open in the default Compose file today.

The README roadmap asks for four things: faster pipelines, mobile and offline dashboards, LLM-assisted querying, and self-service integration tooling. The current architecture blocks the first two and makes the other two harder than they need to be (see [02-architecture-deep-dive.md](02-architecture-deep-dive.md)).

This plan covers four moves the team has asked for:
1. Flask to FastAPI.
2. webpack to Vite.
3. A frontend redesign on HeroUI with the Urbanist typeface.
4. A performance pass across the query path, the pipeline and the warehouse.

## Documents

| File | What it holds |
|---|---|
| [01-current-state.md](01-current-state.md) | What exists today, with file pointers |
| [02-architecture-deep-dive.md](02-architecture-deep-dive.md) | Hot paths, measured inefficiencies, gap analysis against the README goals |
| [03-target-architecture.md](03-target-architecture.md) | The end state and the decisions behind it |
| [04-technology-research.md](04-technology-research.md) | Versions and constraints for each technology as of 2026-10-04, with sources |
| [05-ui-surface-inventory.md](05-ui-surface-inventory.md) | Every screen and `ui/` component, mapped to HeroUI |
| [testing.md](testing.md) | How each phase proves itself |
| [SPEC.md](SPEC.md) | **The binding specification** every agent and engineer follows |
| [TEAM.md](TEAM.md) | The agent team, the skills each agent loads, and how to run the team |

## Scope

**Included.**
- Security fixes and deletion of dead code and dependencies.
- Quick performance wins on the current stack.
- A test harness, Python 3.13 with uv, and CI.
- Separating the query engine and data access from Flask.
- A route-by-route migration from Flask to FastAPI, behind nginx.
- Retiring Hasura and Relay in favour of FastAPI REST with a generated TypeScript client.
- Vite, React 19, Flow to TypeScript.
- A HeroUI v3 design system with Urbanist, and a redesign of every screen listed in the inventory.
- Upgrading Druid, a columnar pipeline, incremental indexing, and an orchestrator.

**Explicitly excluded.**
- Replacing Druid with another warehouse. A ClickHouse prototype is scheduled as a decision gate in phase 8, not as a commitment.
- New product features beyond what the redesign needs.
- Native mobile apps.
- The LLM query feature itself. This plan builds the typed query schema it needs and stops there.
- Transactional email templates, apart from brand colours and font.

## Constraints

- **Deployments run on modest hardware with small teams.** Any change that adds a service has to remove one. See "Cost of ownership" in the README.
- **Stored data carries Potion `$ref` URIs.** Dashboard specs and query selections serialise as `{$ref: '/api2/query/<endpoint>/<id>'}` (for example `web/client/models/core/wip/Dimension/index.js:115`). The new API must read them until a data migration rewrites them.
- **HeroUI v3 needs React 19 and Tailwind CSS v4.** Tailwind v4 needs Chrome 111, Safari 16.4 or Firefox 128 or newer. We have not yet measured which browsers ministry workstations run. Phase 0 collects that from nginx access logs before phase 7 commits.
- **Urbanist covers Latin only and has no tabular figures.** Amharic deployments need Noto Sans Ethiopic as a fallback, and numeric columns need a separate figure face (see [03-target-architecture.md](03-target-architecture.md#typography)).
- **The Ethiopian calendar must keep working** in date pickers, granularities and the backend calendar settings.
- **Translations must keep working.** The `I18N.text` system covers 451 files and the French, Portuguese and Amharic deployments.
- **Each deployment's `config/<code>/` and `pipeline/<code>/` must keep running** throughout. Breakage between phases is acceptable only inside a phase branch, never on `main`.

## Alternatives considered

### How to move from Flask to FastAPI

1. **Rewrite at once.** Port all of the roughly 245 `/api2` endpoints and 40 blueprint handlers, then switch over. This is rejected because there are no tests to catch a regression and the surface is too large for one review.
2. **Mount Flask inside FastAPI with `a2wsgi`.** One process and one port. This is rejected as the primary path because the mounted Flask app would run in a thread pool instead of gevent, which changes the concurrency of every legacy route at once. It also gives a single failure domain.
3. **Run both behind nginx and route by path (chosen).** FastAPI owns a new `/api/v3/` prefix and takes over pages one by one. Flask keeps everything it has not handed over. Both verify the same `accessKey` JWT (`web/server/util/authentication.py:25-57`), so a user moving between them needs no session bridge. When a domain moves, its frontend callers switch to the generated client and the Potion resource is deleted in the same change.

### How to move the frontend to HeroUI

1. **Wrap HeroUI behind the existing `ui/` APIs, then re-skin pages.** Most pages change through one adapter swap, but the old prop shapes stay around forever.
2. **Rebuild each page directly on HeroUI.** This gives clean code but a long period with two visual languages, and every page carries risk.
3. **Two steps, chosen.** First, swap the internals of each high-fan-out `ui/` component (`Button`, `InputText`, `Checkbox`, `Tabs`, `BaseModal`, `Toaster` and so on) to HeroUI behind its current API, so every page picks up the new look together. Then, page by page, migrate callers to HeroUI's own API and delete the `ui/` wrapper once nothing imports it. This follows "migrate callers, then delete".

### Where the frontend ends up

1. **Keep the multi-page app on Vite.** Each Jinja template loads its own entry. This is the cheapest option, but offline dashboards stay out of reach.
2. **Single-page shell with a router and service worker (chosen as the end state).** It is needed for the offline and mobile roadmap item, and it removes about 19 nearly identical templates. It is reached in phase 7f, after every page runs on Vite and HeroUI. Until then the multi-page app stays.

## Applicable skills

- `pstack:how` before changing any unfamiliar subsystem. Run it on the query builder, Potion signals and the Zen model system first.
- `pstack:architect` for the new `AppContext`, the `QueryRequest` Pydantic schema and the design token file.
- `pstack:interrogate` on the auth port (phase 5d) and on the Druid null-handling audit (phase 8a).
- `pstack:tdd` for every bug this plan lists (see [02-architecture-deep-dive.md](02-architecture-deep-dive.md#bugs-found-during-the-dive)).
- `pstack:arena` for the font prototype in phase 7a and the ClickHouse decision gate in phase 8f.
- `frontend-design:frontend-design` for the HeroUI theme and the page redesigns.
- `verify` (Claude Code built-in) for runtime checks on every UI phase. `run` for the CLI and pipeline phases.
- `/deslop` over each diff before committing, `pstack:unslop` over any prose, and `pstack:babysit` after opening each PR.
- `pstack:show-me-your-work` to keep a decision log for phases 5 and 8, which are long enough to need an audit trail.

## Phases

Each phase file lists small, separately shippable units. Every unit ends in a check (see [testing.md](testing.md)). Phases 0 and 1 can start on day one. Phases 6 and 7 can run alongside phase 5 once phase 4 lands.

| Phase | File | Depends on | Rough size |
|---|---|---|---|
| 0. Security and subtraction | [phase-0-security-and-subtraction.md](phase-0-security-and-subtraction.md) | nothing | 1 to 2 weeks |
| 1. Performance quick wins | [phase-1-performance-quick-wins.md](phase-1-performance-quick-wins.md) | nothing | 1 to 2 weeks |
| 2. Test harness and toolchain | [phase-2-test-harness-and-toolchain.md](phase-2-test-harness-and-toolchain.md) | 0 | 2 to 3 weeks |
| 3. Python 3.13 and the dependency floor | [phase-3-python-and-dependency-floor.md](phase-3-python-and-dependency-floor.md) | 2 | 3 to 4 weeks |
| 4. Decouple the core from Flask | [phase-4-decouple-core-from-flask.md](phase-4-decouple-core-from-flask.md) | 3 | 3 to 4 weeks |
| 5. FastAPI, domain by domain | [phase-5-fastapi-migration.md](phase-5-fastapi-migration.md) | 4 | 3 to 4 months |
| 6. Frontend platform: fetch, Vite, React 19, TypeScript | [phase-6-frontend-platform.md](phase-6-frontend-platform.md) | 0 | 6 to 8 weeks, TypeScript continues after |
| 7. Design system: HeroUI and Urbanist | [phase-7-design-system.md](phase-7-design-system.md) | 6c | 3 to 4 months |
| 8. Data platform: Druid, pipeline, orchestration | [phase-8-data-platform.md](phase-8-data-platform.md) | 3 | 2 to 3 months |

## Verification

Project-level commands once phase 2 lands:

```
uv run pytest                      # backend unit, contract and golden tests
uv run mypy                        # typed backend packages
uv run ruff check && uv run ruff format --check
pnpm test                          # Vitest
pnpm typecheck                     # flow check now, tsc once phase 6e starts
pnpm lint
pnpm build                         # Vite production build and manifest
pnpm e2e                           # Playwright smoke suite against docker compose
```

Runtime verification for each UI phase uses the `verify` skill against `make up DEV=1` with the `harmony_demo` deployment. Pipeline phases use the `run` skill against `pipeline/harmony_demo`.

## Implementation guidance

Each phase owner must apply these poteto-mode rules:
- Run **how** over each subsystem before changing it.
- Run **interrogate** before shipping the auth port, the `$ref` data migration and the Druid upgrade.
- Run `/deslop` over every diff and **unslop** over every prose change.
- Follow **migrate callers, then delete legacy APIs** inside each phase. No Potion resource, `ui/` wrapper or SCSS partial should outlive the phase that replaced it.
- Use **show-me-your-work** for phases 5 and 8.
- Run **babysit** after every PR is opened.

These principles shaped the plan:
- **Subtract before you add** put deleting dead code and closing exposures first (phase 0), ahead of any new framework.
- **Sequence verifiable units** put the test harness (phase 2) ahead of every dependency bump. It also means each domain move in phase 5 ships with contract tests recorded against Flask first.
- **Outcome-oriented execution** means each migration targets the end state and deletes the old path in the same wave. No permanent compatibility layer is planned. The one deliberate exception is the `$ref` reader, which is time-boxed and removed after a data migration.
- **Exhaust the design space** picked nginx path routing over `a2wsgi` mounting. It also requires a typography prototype before the font is locked in.
- **Experience first** made the target frontend a single-page shell with offline support, and made tabular figures a hard requirement.
