---
name: differential-oracle-method
description: How to prove INV-2 across a dependency or interpreter bump beyond the recorded golden data (base-tree oracle env plus seeded synth fuzz)
metadata:
  type: reference
---

Method that worked in WP-3b for proving "results unchanged" across pandas 1.5 -> 2.2 and a JSON parser swap:

1. Oracle env: `git archive <pre-bump commit> | tar -x -C /tmp/x` then `uv sync --locked` there (separate venv with the old lock). Golden passes there first.
2. Run the same script in both envs with `uv run --project <tree> python script.py <tree> ...`; the script `sys.path.insert(0, tree)` and `chdir`s, so each env runs its own code.
3. Fuzz beyond fixtures: `tests.golden.harness.run_case(case, lambda q: synthesize(f'{case.name}#seedN', q, options))` with `special_values` on and off; compare body sha256 per variant. 20 seeds x 85 cases = 3300 variants in ~1 min.
4. Mutation check: revert the fix in a copy and confirm the fuzz diverges (it did: 134/825), so the check has teeth.

Scripts are kept in `docs/modernisation/work/WP-3b-evidence/core/` (fuzz.py, merge_diff.py, edge_parse.py, parse_bench.py, memory_bench.py, e2e_bench.py).

Related: [[pandas2-inv2-traps]], [[worktree-isolation-hook-workarounds]].
