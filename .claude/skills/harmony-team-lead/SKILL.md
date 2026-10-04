---
name: harmony-team-lead
description: Runbook for the lead session that orchestrates the Harmony migration team. Use when starting or continuing the modernisation, choosing which work packages run next, spawning builder, QA, reviewer or security agents, routing cross-role requests, or checking whether a WP may close.
---

# Leading the Harmony migration team

You coordinate. Builders build, QA proves, reviewers judge. You do not write production code in a lead session. The team, the skills each member loads, and the start-up steps are in `docs/modernisation/TEAM.md`. The rules are in `docs/modernisation/SPEC.md`.

## Pick the next wave

1. List each WP's state:
   ```bash
   ls docs/modernisation/work/
   grep -h '^status:' docs/modernisation/work/WP-*.md
   ```
2. A WP is ready to start when every WP in its "Depends on" column (SPEC section 5) is `done` or merged.
3. Choose 3 to 5 WPs that touch different roles. Two builders of the same role are fine only when their WP files list disjoint `files:`.
4. Start with WPs that remove risk:
   - **Wave 1:** 0a, 0b, 0c, 0d, 0e, 0f, 0g.
   - **Wave 2:** 1a and 2a to 2e (the test harness).
   - **Wave 3:** the rest of phase 1, plus 2f and 2g.
   - After WP-4f, the backend (5x), frontend (6x then 7x) and data (8x) streams run in parallel.

## Spawn the team

**Agent teams mode.** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set in project settings, and the session must be interactive.
- Spawn each teammate by agent type and name, one WP each. For example: "Spawn a teammate named core-1 using the harmony-core-engineer agent type. Assignment: WP-1b. Load harmony-migration-protocol first."
- Teammates do not receive the `skills:` preload from their definition. Every agent body tells it to load its skills with the Skill tool, and path-scoped rules in `.claude/rules/` reinforce this. Confirm in a teammate's first report that it loaded them.
- Teammates share your checkout. Each must create its own git worktree (protocol step 2). Check `git worktree list` after spawning.
- Create one top-level task `WP-<id>: <title>` per WP. The `TaskCompleted` hook (`scripts/agents/task_gate.py`) blocks completion until the WP file shows the required approvals and the branch respects ownership.

**Subagent mode** (non-interactive, or when teams are off).
- Dispatch with the Agent tool: `subagent_type: harmony-<role>-engineer`, run in the background, prompt `Assignment: WP-<id>. Follow harmony-migration-protocol.` Agent definitions preload their skills, run their own ownership hook, and use `isolation: worktree`.
- Dispatch independent WPs in one message so they run concurrently.

## Run the gates

When a builder sets `status: review`, dispatch these in parallel on the WP branch:
- `harmony-qa-engineer`,
- `harmony-code-reviewer`,
- `harmony-security-reviewer`, when the WP file has `security_review: true`.

Each writes its verdict into the WP file. Re-dispatch the builder with the consolidated findings. Do not forward three separate reports.

Check the gate yourself before telling the human a WP is ready:
```bash
python3 scripts/agents/task_gate.py WP-<id>
```

## Route requests

Read the Requests sections:
```bash
grep -A20 '^## Requests' docs/modernisation/work/WP-*.md | grep '\- \[ \]'
```
Turn each open request into a task, or a dispatch, for the owning role. If two roles disagree after one exchange, decide when the spec is clear. Otherwise put the question to the human.

## Report to the human

Report per wave:
- WPs moved and to what status;
- PRs ready to merge, with their requirement IDs;
- blocked WPs, with the exact question;
- the next wave.

The human merges and runs anything irreversible.

## Keep the system honest

- **Spec gaps.** If a rule keeps being restated in messages, propose an edit to SPEC or a skill in `docs/modernisation/decisions/`. Do not repeat the instruction a third time.
- **Ownership gaps.** If ownership blocks legitimate work, fix the table in SPEC section 6 through a decision. Never grant a one-off exception.
- **Vendored skills.** Refresh them with `scripts/agents/update_vendored_skills.sh` and review the diff before committing.
- **Plugins.** Install them on a new machine with `scripts/agents/install_plugins.sh`.
