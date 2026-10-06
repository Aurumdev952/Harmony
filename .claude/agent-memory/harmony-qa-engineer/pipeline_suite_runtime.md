---
name: pipeline-suite-runtime
description: How to run the pipeline fixture suite (process_csv, fill_dimension_data) on the host; root lock 3.13 only, binaries
metadata:
  type: project
---

Since WP-3b (2026-10-06), `tests/pipeline/run.sh` runs on the root `uv.lock` environment (CPython 3.13, as the pipeline image and `ci/pytest_suites.sh`); WP-3a's `find_spec` hook made `config/` importable on 3.12+. It gives 130 passed under `CI=1`, and `run.sh regenerate` on 3.13 rewrites the 367 goldens byte-identically. The `PIPELINE_FIXTURE_PYTHON` override and `tests/pipeline/requirements.txt` were deleted at WP-3b's close (infra, lead's follow-up 6): no image runs 3.9 or PyPy any more. For a pre-WP-3b comparison, run the suite from a `git archive` of a pre-WP-3b commit with its own lock.

**Why:** PyPy and CPython 3.9 output was byte-identical for all WP-2d cases, and WP-3b's pipeline image is CPython 3.13 only, so the 3.13 run is the one that matches production.

**How to apply:** for any pipeline-touching WP verdict (8d, 8e), run `CI=1 tests/pipeline/run.sh`. `mutation_check.py` copies the tree without `.venv`, so each mutant's run syncs a fresh env from the uv cache (7 mutants took about 14 minutes on 2026-10-06). Needs lz4/lz4cat on PATH; pigz is shimmed to gzip. Steps must run one subprocess per invocation (module-level caches, global Flags) and never with -O (asserts are control flow). Prove sensitivity by mutating a copy of the tree in /tmp (rsync excluding .git/node_modules), never production files. See [[worktree-guard-bash]].
