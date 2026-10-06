---
name: pipeline-suite-runtime
description: How to run the pipeline fixture suite (process_csv, fill_dimension_data) on the host; root lock 3.13 default, 3.9/PyPy override, binaries
metadata:
  type: project
---

Since WP-3b (2026-10-06), `tests/pipeline/run.sh` runs on the root `uv.lock` environment (CPython 3.13, as the pipeline image and `ci/pytest_suites.sh`); WP-3a's `find_spec` hook made `config/` importable on 3.12+. `PIPELINE_FIXTURE_PYTHON=3.9|pypy3.9` still runs with `tests/pipeline/requirements.txt` (future 1.0.0; 0.18.3 imports `imp`, gone in 3.12). All three give 130 passed under `CI=1`, and `run.sh regenerate` on 3.13 rewrites the 367 goldens byte-identically.

**Why:** PyPy and CPython 3.9 output was byte-identical for all WP-2d cases, and WP-3b's pipeline image is CPython 3.13 only, so the 3.13 run is the one that matches production.

**How to apply:** for any pipeline-touching WP verdict (8d, 8e), run `CI=1 tests/pipeline/run.sh`, and for a before/after comparison with the pre-WP-3b runtime also `PIPELINE_FIXTURE_PYTHON=pypy3.9`. `mutation_check.py` copies the tree without `.venv`, so each mutant's run syncs a fresh env from the uv cache (7 mutants took about 14 minutes on 2026-10-06). Needs lz4/lz4cat on PATH; pigz is shimmed to gzip. Steps must run one subprocess per invocation (module-level caches, global Flags) and never with -O (asserts are control flow). Prove sensitivity by mutating a copy of the tree in /tmp (rsync excluding .git/node_modules), never production files. See [[worktree-guard-bash]].
