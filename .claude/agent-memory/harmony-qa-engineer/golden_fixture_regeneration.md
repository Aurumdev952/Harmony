---
name: golden-fixture-regeneration
description: How to regenerate golden druid_query.json fixtures for a deliberate query-text change (INV-2) and prove nothing else moved; traps from WP-8a N1/N2 (2026-10-05)
metadata:
  type: project
---

Procedure that worked for WP-8a (76 cases, N1 `selector value null` and N2 `and(leaf, not(selector dim null))` under `not`):
1. Before: `record.py --check` list must equal the `test_druid_queries` failures from pytest, and every listed file must be `druid_query.json`.
2. Snapshot sha256 of every `tests/golden/cases/*/*.json`, then run `record.py <named cases>` only. Never run it bare: it would rewrite all three fixtures.
3. After: every non-`druid_query.json` file must keep its hash (`record.py` also rewrites `druid_response.json` from `synth`, so check it too). `record.py --check` must report 0 changes, `tests/golden` must pass, and the result must hold under a `PYTHONHASHSEED` sweep.
4. Prove the pattern with your own "undo" script. Revert the accepted rewrite on each new fixture and compare it with `git show <base>:<path>` modulo the harness's and/or operand sort. A wrapper node such as N2's `and` re-sorts its parent's operands, so a strict comparison gives false alarms.

**Trap:** owner drift tools that apply the rewrite to fixtures (`scripts/druid/null_audit/check_fixture_drift.py`) are not idempotent. After regeneration they report "other differences" on the N2 cases and exit 1. This is expected. Report it to the owner and do not "fix" fixtures to satisfy it.

**Proving a new case catches a fix's absence without editing production files** (hook-owned): run `git archive -o /tmp/x.tar <base>` alone, then extract it to /tmp, run `git show <fix> -- data db > fix.patch` and `patch -R -p1` in the scratch tree, and copy the new case in. Run with `UV_PROJECT_ENVIRONMENT=<worktree>/.venv uv run --frozen pytest tests/golden` so the scratch tree reuses the worktree's venv. Synth answers like legacy Druid, so for null-semantics fixes only `test_druid_queries` fails. The response tests stay green, and that is expected.

**Why:** a regeneration changes what INV-2 compares against, so the evidence must show only the intended forms moved. **How to apply:** any WP that changes posted query text (8a, 8b, 4x). See [[golden-suite-harness]] and [[golden-verdict-mutants]].
