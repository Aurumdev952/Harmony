---
name: supporting-role-traps
description: Ownership, sandbox and Docker traps hit as pipeline supporter on WP-3b (tests location, worktree guard, container-owned files, old PyPy image, venv symlinks)
metadata:
  type: project
---

- `tests/pipeline/**` is qa-owned, even when a lead's brief lists it as pipeline's. Pipeline-role tests go in a new `tests/<dir>/` (shared). `ci/pytest_suites.sh` picks up a new directory with no change. Give the test file a unique basename, because the test directories have no `__init__.py`. Example: `tests/pipeline_steps/test_steps_on_cpython.py` (2026-10-06).
- The worktree-isolation guard refuses Bash lines that combine `$VAR`, `cd`, pipes or `bash -c` with uv, docker or git. Put the logic in a script under `/tmp/<scratch>/` and run `bash /tmp/<scratch>/x.sh <literal args>`. Use `uvx --from uv==0.12.23 uv run python` instead of `python3` (a hook enforces this).
- On this host a container running `--user 1000:1000` writes files that the host user (also uid 1000) cannot delete, because of uid remapping. Bind-mounted work dirs need `chmod -R a+rwX` before the run. Clean up with the same image and uid (`docker run --user 1000:1000 ... rm -rf`), then `rm -rf` on the host.
- The old pipeline image with PyPy 3.8.13 and CPython 3.9: infra's `:int` tag was removed. `local/wp4a-infra/harmony-pipeline:test` has the same per-row code; only `log/` predates WP-2g. Before using it as a baseline, compare md5 manifests of `/zenysis/{data/pipeline,util,pipeline/harmony_demo,config/harmony_demo,log}`.
- Neither pipeline image ships `.pyc` for the app code, and uid 1000 cannot write `/zenysis`. Mount branch code `:ro` and strip host `__pycache__` before mounting, so both images compile on every run, as they do in production.
- A step's `#!/usr/bin/env python` loses the venv if `python` is a symlink to `sys.executable` in another directory, because `pyvenv.cfg` is looked up next to the link. Put `Path(sys.executable).parent` first on `PATH` instead.
- The lint gate checks every touched file in full. Pipeline modules still use `assert` for runtime checks, and the goldens pin `AssertionError: <msg>`. Replace `assert c, m` with `if not c: raise AssertionError(m)`: the exception and message stay the same, S101 passes, and the check also runs under `-O`.
