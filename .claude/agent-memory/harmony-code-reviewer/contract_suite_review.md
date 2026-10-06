---
name: contract-suite-review
description: How to review tests/contract (WP-2c and any WP that re-records); offline probes of schema.diff, coverage stats over recordings, and the cross-WP conflicts that break test stacks
metadata:
  type: project
---

Lessons from reviewing WP-2c on 2026-10-04 (verdict changes-requested).

- **Probe the schema offline.** Write a small script under /tmp and run it with `PYTHONPATH=<scratch worktree> uv run --no-project python /tmp/x.py`. Call `infer`/`diff`/`observe`/`compare` directly. No stack is needed to show what replay accepts or rejects.
- **Coverage is in the recordings, not the cases.** Walk every `response_schema` and count:
  - `maxItems: 0` arrays;
  - `properties: {}` objects;
  - `type: string` leaves with no pin.

  Collections that are empty in every recording have no pinned item shape. At WP-2c that was user and group `acls`, `apiTokens`, group `roles`, alert `filters`, and `digest_overview` returning `{}`. A port can rename fields inside them and still pass.
- **Enums are not part of the shape.** `diff` ignores string values, and `pin` takes only scalar pointers, so a value renamed inside an array passes replay.
- **Cross-WP breakage.** A test stack that re-declares production services stops starting once these land:
  - WP-0b requires `REDIS_PASSWORD` whenever `REDIS_HOST` is set, plus a `JWT_SECRET_KEY` different from `DEFAULT_SECRET_KEY`.
  - WP-0a's proxy refuses to call Hasura without `HASURA_ADMIN_SECRET`.

  Check every new compose file against the open 0a/0b branches.
- **WP-2f lock.** It has no `hypothesis`, so any suite that imports it aborts the whole `pytest -m 'not stack'` collection. Its ruff `line-length` is 88 and `ci/lint_python.sh` runs `ruff format --check` on changed files. Evidence that used `--line-length 120` hides this.
- **WP-0a's Relay replay.** `scripts/db/hasura/replay_relay_operations.py` already replays all 51 Relay operations with realistic variables. Use it to check the GraphQL coverage claims in the contract suite.

**Why:** each of these looked fine from the diff alone. Each became concrete only through a probe or a sibling branch.
**How to apply:** use this when reviewing tests/contract, any phase-5 router that replays it, or any new test stack. See [[review-traps]] for the worktree-guard limits on Bash.
