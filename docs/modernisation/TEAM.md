# The migration team

Back to [SPEC.md](SPEC.md).

Eleven Claude Code agents carry out the migration:
- **Eight builders**, one per part of the stack.
- **Three gatekeepers:** QA, code review and security.

Each role works independently inside its own paths and work packages. Roles collaborate through:
- shared contracts (SPEC section 4);
- per-WP files (`work/WP-*.md`);
- under agent teams, the shared task list and direct messages.

Several instances of one role can work at once on separate WPs, or on disjoint files within one WP.

## Roster

| Agent | Role | Model | Preloaded skills |
|---|---|---|---|
| `harmony-core-engineer` | core | opus | `harmony-migration-protocol`, `harmony-query-engine`, `harmony-sqlalchemy-alembic`, `pydantic:pydantic`, `astral:uv`, `astral:ruff`, `modern-python:modern-python` |
| `harmony-backend-engineer` | backend | opus | `harmony-migration-protocol`, `harmony-fastapi`, `fastapi`, `pydantic:pydantic`, `harmony-sqlalchemy-alembic`, `harmony-celery`, `redis-development:redis-core`, `astral:uv` |
| `harmony-frontend-platform-engineer` | frontend-platform | opus | `harmony-migration-protocol`, `harmony-frontend`, `pstack:typescript-best-practices`, `router-core`, `router-plugin`, `router-query` |
| `harmony-frontend-design-engineer` | frontend-design | opus | `harmony-migration-protocol`, **`frontend-design:frontend-design`**, `harmony-design-system`, `heroui-react`, `pstack:typescript-best-practices`, `storybook:stories` |
| `harmony-visualization-engineer` | visualization | opus | `harmony-migration-protocol`, `harmony-visualization`, `dataviz`, `harmony-design-system`, `maplibre-v6-migration`, `maplibre-source-wiring` |
| `harmony-data-platform-engineer` | data-platform | opus | `harmony-migration-protocol`, `harmony-druid`, `harmony-query-engine`, `docker-skills:docker-compose-patterns`, `clickhouse-best-practices:clickhouse-best-practices` |
| `harmony-pipeline-engineer` | pipeline | opus | `harmony-migration-protocol`, `harmony-pipeline`, `polars:polars`, `dagster:dagster-expert`, `astral:uv`, `property-based-testing:property-based-testing` |
| `harmony-infra-engineer` | infra | opus | `harmony-migration-protocol`, `harmony-infra`, `docker-skills:docker-project-foundations`, `docker-skills:docker-build-strategies`, `docker-skills:docker-compose-patterns`, `docker-skills:docker-destructive-guardrails`, `astral:uv`, `astral:ruff` |
| `harmony-qa-engineer` | qa | opus | `harmony-migration-protocol`, `harmony-qa`, `harmony-query-engine`, `pstack:tdd`, `property-based-testing:property-based-testing` |
| `harmony-code-reviewer` | reviewer | opus | `harmony-migration-protocol`, `harmony-review`, plus the area skill of the code under review |
| `harmony-security-reviewer` | security | fable | `harmony-migration-protocol`, `harmony-security`, `differential-review:differential-review`, `sharp-edges:sharp-edges`, `static-analysis:semgrep`, `fp-check:fp-check`, `supply-chain-risk-auditor:supply-chain-risk-auditor` |

The definitions live in `.claude/agents/`.

**What every agent definition sets:**
- `memory: project`: lessons persist per role in `.claude/agent-memory/<agent>/`.
- `isolation: worktree`: applies when the agent runs as a subagent.
- `skills:`: preloads its skills in subagent mode.

**Workflow skills, invoked when needed** (not preloaded):
- every role: `pstack:how`, `pstack:tdd`, `pstack:interrogate`, `/deslop`, `verify`, `run`;
- the frontend design engineer: `pstack:arena`, for the typography prototype.

The frontend design engineer must start every visual task with `/frontend-design:frontend-design`. Its agent body, its preload list and the path rule for `web/client/components/**` all enforce this.

## Where the skills come from

The research pass (2026-10-04) checked each tool's official docs and GitHub organisation for a vendor-published skill. Where one exists, the team uses it. Where none exists, there is a custom `harmony-*` skill grounded in the vendor's docs.

| Tool | Official skill or integration | How the team gets it | Custom overlay |
|---|---|---|---|
| HeroUI v3 | Yes: `heroui-react` skill, and the `@heroui/react-mcp` MCP server | Skill vendored in `.claude/skills/heroui-react`. MCP pinned in `.mcp.json` | `harmony-design-system` |
| Frontend design | Yes: Anthropic `frontend-design` | Plugin `frontend-design@claude-plugins-official` | `harmony-design-system` |
| Tailwind CSS v4 | No (the project declined both llms.txt and a skill) | n/a | facts in `harmony-design-system` |
| React 19 | Partial (react.dev's skills are for its own docs) | n/a | `harmony-frontend` (`references/react19.md`) |
| Vite 8, Vitest 5 | No official skill | n/a | `harmony-frontend` (`vite.md`, `testing.md`) |
| TypeScript | No | `pstack:typescript-best-practices` | `harmony-frontend` (`typescript.md`) |
| TanStack Router | Yes: skills shipped with the packages | Vendored: `router-core`, `router-plugin`, `router-query` | `harmony-frontend` (`data-layer.md`) |
| TanStack Query, hey-api | No | n/a | `harmony-frontend` (`data-layer.md`) |
| visx | No | `dataviz` (built-in) | `harmony-visualization` |
| MapLibre | Yes (MapLibre organisation, community-maintained) | Vendored: `maplibre-v6-migration`, `maplibre-source-wiring` | `harmony-visualization` |
| Storybook | Yes: plugin, and the `@storybook/addon-mcp` addon | Plugin `storybook@storybook`. The addon MCP gets added in WP-6d | `harmony-frontend` (`testing.md`) |
| Playwright | Yes: MCP and CLI skills | Plugin `playwright@claude-plugins-official` | `harmony-qa` |
| FastAPI | Yes: bundled in the package | Vendored `.claude/skills/fastapi` | `harmony-fastapi` (overrides SQLModel and ty) |
| Pydantic | Yes | Plugin `pydantic@pydantic-skills` | n/a |
| SQLAlchemy, Alembic | No | n/a | `harmony-sqlalchemy-alembic` |
| Celery | No | n/a | `harmony-celery` |
| Redis | Yes | Plugin `redis-development@claude-plugins-official` | `harmony-celery` |
| uv, ruff | Yes (Astral) | Plugin `astral@astral-sh` | `harmony-infra` |
| Apache Druid | No skill and no official MCP | n/a | `harmony-druid` |
| Polars | Yes | Plugin `polars@polars` | `harmony-pipeline` |
| Dagster | Yes | Plugin `dagster@dagster` | `harmony-pipeline` |
| Docker | Yes | Plugin `docker-skills@docker` | `harmony-infra` |
| ClickHouse (decision gate) | Yes | Plugin `clickhouse-best-practices@claude-plugins-official` | `harmony-druid` |
| GitHub Actions, nginx, OpenTelemetry, Authlib | No | n/a | `harmony-infra`, `harmony-fastapi` |
| Security tooling | Yes: Trail of Bits, Anthropic | Plugins `differential-review`, `sharp-edges`, `insecure-defaults`, `static-analysis`, `fp-check`, `supply-chain-risk-auditor` (all `@trailofbits`), `claude-security` and `security-guidance` (`@claude-plugins-official`) | `harmony-security` |
| Python practice, property tests | Yes (Trail of Bits) | `modern-python@trailofbits`, `property-based-testing@trailofbits` | n/a |

**Coordination skills** (custom, used by every role):
- `harmony-migration-protocol`: how to claim, build, request and close a WP;
- `harmony-team-lead`: the lead's runbook;
- `harmony-qa`, `harmony-review`, `harmony-security`: the gatekeepers' procedures;
- `harmony-query-engine`: the domain knowledge most roles need.

Vendored skills are pinned in `.claude/skills/VENDORED.lock` and keep their upstream licences (Apache-2.0 or MIT). `scripts/agents/update_vendored_skills.sh` refreshes them. Review the diff before committing it, because vendored skills become agent instructions.

## One-time setup per machine

1. Open the repository in Claude Code and accept the workspace trust prompt. Project plugins, hooks and the agent-teams setting only apply after trust.
2. Install the plugins: `scripts/agents/install_plugins.sh`. It reads the marketplaces and plugins from `.claude/settings.json`.
3. Approve the `heroui-react` MCP server when Claude Code asks. It is declared in `.mcp.json`.
4. Check the wiring: `python3 scripts/agents/check_team.py` must report `0 problems`.
5. Restart Claude Code, so the agents in `.claude/agents/` and the plugins load.

## Running the team

Start a lead session and load `harmony-team-lead`. The lead never writes production code. It:
- picks a wave of WPs whose dependencies are done;
- spawns one builder per WP;
- dispatches the gatekeepers when a WP reaches review;
- routes requests;
- reports to the human, who merges.

### Mode A: agent teams (interactive sessions, recommended)

`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set in `.claude/settings.json`. Example lead prompt:

> Load harmony-team-lead. Start wave 1. Spawn teammates using these agent types:
> - infra-1 (harmony-infra-engineer) on WP-0b;
> - core-1 (harmony-core-engineer) on WP-0c;
> - fe-platform-1 (harmony-frontend-platform-engineer) on WP-0e;
> - backend-1 (harmony-backend-engineer) on WP-0a.
>
> Create one task per WP named `WP-<id>: <title>`. When a WP reaches review, spawn qa-1, reviewer-1 and, for Sec WPs, security-1 to review it.

How teams mode behaves, according to the Claude Code docs:
- **Skill preloads don't apply.** Teammates take the definition's tools, model and prompt body, but not the `skills:` preload. Every agent body therefore starts by loading its skills explicitly. The path rules in `.claude/rules/` remind any session touching an area which skills to load.
- **Worktrees are manual.** Teammates share the lead's checkout, and `isolation` does not apply. The protocol has each teammate create its own git worktree. The ownership hook and per-WP `files:` claims keep teammates off each other's files.
- **Size.** Keep 3 to 5 teammates active, with 5 or 6 tasks each.
- **Gate.** The `TaskCompleted` hook refuses to close a `WP-<id>:` task until the WP file shows the required approvals and the branch passes the ownership check.

### Mode B: subagents (non-interactive sessions, CI, or teams switched off)

The lead dispatches agents with the Agent tool, in the background, several per message:

> Agent(subagent_type: "harmony-core-engineer", prompt: "Assignment: WP-1b. Follow harmony-migration-protocol.")

In this mode:
- skill preloads, `isolation: worktree` and project memory all apply;
- collaboration runs through the WP files' Requests sections, which the lead routes.

## How the pieces enforce the spec

| Rule | Enforced by |
|---|---|
| Edit only your role's paths (SPEC 6) | PreToolUse hook `scripts/agents/ownership.py hook`, keyed on the agent type. The `check` mode runs at review time and inside the completion gate. |
| A WP closes only with approvals and clean ownership (SPEC 8) | TaskCompleted hook `scripts/agents/task_gate.py` |
| No merge, force-push, deploy or `.env` reads | `permissions.deny` in `.claude/settings.json` |
| Skills exist for every agent | `scripts/agents/check_team.py` |
| One source of ownership truth | The machine-read table in SPEC section 6 |

## Known limits

- **Agent teams are experimental.** In-process teammates are not restored by `/resume`, and task status can lag.
- **Unconfirmed hook behaviour for teammates.** The docs confirm that hook input carries `agent_type` for subagents, but not whether it does for teammates. Until that is confirmed, the completion gate and the reviewer's `ownership.py check` are the backstop.
- **Version facts age.** The skills tell agents to confirm versions against the installed package or the official docs before relying on a detail.
