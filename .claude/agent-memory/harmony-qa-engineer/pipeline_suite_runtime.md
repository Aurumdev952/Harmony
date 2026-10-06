---
name: pipeline-suite-runtime
description: How to run Harmony pipeline step scripts (process_csv, fill_dimension_data) on the host; Python version, PyPy parity, binaries
metadata:
  type: project
---

Pipeline step scripts run on the host under uv with Python 3.9 (`tests/pipeline/run.sh`); 3.12+ fails at `import config.*` because `config/__init__.py` ConfigImporter only has find_module/load_module (request filed to core in WP-2d, 2026-10-04).

**Why:** no pypy3 on the host and the pipeline image is CPython 3.9.16 + PyPy 3.9; `uv python install pypy3.9` works and PyPy output was byte-identical to CPython for all 25 WP-2d cases, so CPython goldens are valid.

**How to apply:** for any pipeline-touching WP verdict (8d, 8e), run `tests/pipeline/run.sh` and `PIPELINE_FIXTURE_PYTHON=pypy3.9 tests/pipeline/run.sh`. Needs lz4/lz4cat on PATH; pigz is shimmed to gzip. Steps must run one subprocess per invocation (module-level caches, global Flags) and never with -O (asserts are control flow). Prove sensitivity by mutating a copy of the tree in /tmp (rsync excluding .git/node_modules), never production files. See [[worktree-guard-bash]].
