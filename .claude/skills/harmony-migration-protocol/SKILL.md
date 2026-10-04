---
name: harmony-migration-protocol
description: The operating protocol for every agent on the Harmony modernisation team. Load it before claiming, building, reviewing or closing any work package (WP), and whenever you need to coordinate with another role, change a shared contract, or decide whether you may edit a path.
---

# Harmony migration protocol

`docs/modernisation/SPEC.md` is the authority. Read sections 2 (invariants), 4 (contracts), 5 (your WP row), 6 (ownership), 7 (protocol) and 8 (definition of done) before you start. When this skill and the spec disagree, the spec wins.

## Before any edit

1. Know your role. Your agent name maps to a role: `harmony-core-engineer` is `core`, `harmony-code-reviewer` is `reviewer`, and so on (see `scripts/agents/ownership.py`, `AGENT_ROLES`).
2. Check ownership of every file you intend to touch:
   ```bash
   python3 scripts/agents/ownership.py who <path> [<path>...]
   ```
   A PreToolUse hook blocks edits outside your role. If it blocks you, do not work around it with Bash. Request the change (below).
3. Read the WP's phase file (`docs/modernisation/phase-*.md`) and the subsystem's code. Run `pstack:how` on any subsystem you have not read this session.

## Claim and work a WP

1. **Claim.**
   ```bash
   cp docs/modernisation/work/_template.md docs/modernisation/work/WP-<id>.md
   ```
   Fill the front matter: `status: claimed`, your role and instance name (`core-1`), `requirements`, `contracts_*`, and `security_review` from the spec's Sec column. If the file already exists with another owner and no free files, pick another WP.
   - Under agent teams, also claim the task `WP-<id>: <title>` in the shared list. Name unit tasks `WP-<id>.<n>: <unit>`. Only the top-level task is gated.
2. **Isolate.** Work on your own branch in your own worktree.
   - **Already in a worktree** (subagent mode with `isolation: worktree`; check with `git rev-parse --show-toplevel`): create the branch there with `git switch -c mig/WP-<id>-<slug>`.
   - **Otherwise** (teammate mode, which shares the lead's checkout):
     ```bash
     git worktree add ../harmony-wt/WP-<id>-<instance> -b mig/WP-<id>-<slug>
     ```
     Use absolute paths into that worktree for every edit and command.
   - Never commit on `main`.
   - Several instances on one WP each take their own branch, `mig/WP-<id>-<slug>-<instance>`, and list disjoint `files:` in the WP front matter.
3. **Plan.** Write the units in the WP file. Each unit is one change plus the check that proves it. Set `status: building`.
4. **Build unit by unit.**
   - Rebase on `main`.
   - Make the change.
   - Run lint, type check and the unit tests for the touched area.
   - Run the surface check: `verify` for UI, `run` for CLI and pipeline, contract replay for API.
   - Run `/deslop` over the diff.
   - Commit as `WP-<id>: <imperative summary>`.
   - Append one line to the WP log.
   - Never start the next unit while this one is red.
5. **Evidence.** Link test output, screenshots, perf samples and `verify` notes under Evidence. A claim with no evidence counts as not done.
6. **Review.** Set `status: review`. Ask `harmony-qa-engineer`, `harmony-code-reviewer` and, if `security_review: true`, `harmony-security-reviewer` to review the branch. Under teams, send each a message. Without teams, the lead dispatches them.
7. **Iterate.** On `changes-requested`, fix, re-run the checks, and ask again.
8. **Ready.** When every required verdict is `approved`:
   - Set `status: ready`.
   - Push the branch.
   - Open a PR whose body lists requirement IDs, evidence and deferrals.
   - Then mark the top-level task complete. The TaskCompleted hook (`scripts/agents/task_gate.py`) refuses completion until the verdicts and ownership checks pass. Run it yourself first: `python3 scripts/agents/task_gate.py WP-<id>`.

## Needing something from another role

- **Under agent teams.** `SendMessage` the owning teammate with the exact change, why, and which unit it blocks. Create a task `WP-<id>.<n>: request for <role>: <change>` owned by them.
- **Without teams.** Add `- [ ] <role>: <change> (blocks unit N)` under Requests in your WP file and set `status: blocked` if nothing else can proceed. The lead routes it.
- Keep working on units that do not depend on the request.

## Changing a contract (C-1 to C-11)

Only the contract owner edits it.
1. Write the old shape, new shape, consumers and migration under "Contract changes".
2. Get an acknowledgement line from each consuming role in that section.
3. Land producer and consumers together. Never leave a contract half-migrated, and never keep both shapes alive past the WP.

## Stop and ask the human

Set `status: blocked` and write the question in the WP file. Do this when:
- an invariant or requirement conflicts with the work;
- you need a secret, production data or a production system;
- an irreversible action is needed (merge, deploy, data migration on real data);
- you and another role still disagree after one exchange.

Never merge to `main`, force-push, deploy, or read `.env`. Settings deny these.

## Reporting back

End every turn with:
- the WP and its status;
- the units finished, with their checks;
- open requests;
- the next unit.

Keep it to a few sentences. The WP file holds the detail.
