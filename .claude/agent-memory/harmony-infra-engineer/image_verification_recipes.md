---
name: image-verification-recipes
description: How to build Harmony images in parallel with other agents and sweep imports inside them; pipeline PyPy cryptography pin; dummy env the web app needs
metadata:
  type: project
---

- **Unique build names.** `DOCKER_NAMESPACE=local/<wp>-<instance> DOCKER_TAG=<x> docker compose -p <wp>-<instance>-<x> -f docker-compose.build.yaml build <service>` keeps images apart from other agents on the shared rootless daemon.
- **Worktree guard and docker.** `docker run` lines that use shell variables, Go templates (`{{.Name}}`) or `bash -c` loops are refused. Write the commands to `/tmp/<wp>/*.sh` and run them with `bash <file>`.
- **WP-0d sweep scripts** (`docs/modernisation/work/WP-0d-evidence/import_sweep.py`, `route_map.py`): when you mount them at `/sweep.py`, also pass `-e PYTHONPATH=/zenysis`, or every module fails with `No module named 'config'`. `route_map.py` also needs dummy `DRUID_HOST`, `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `DATABASE_URL`. Sort the output and keep only lines that contain a tab; some modules print `PASS:` lines at import.
- **Overlaying another role's unmerged deletion:** bind-mount a patched copy read-only (`-v /tmp/.../web/server:/zenysis/web/server:ro`). Never edit their paths in your branch.
- **The pipeline image (`docker/pipeline/Dockerfile`) installs PyPy with `--no-build-isolation`.** Any dependency that ships only an sdist with a PEP 517 backend (maturin, for example) fails there. Ubuntu 22.04's PyPy 7.3.9 also aborts (`Fatal RPython error ... PyThreadState_Swap`) when it imports `cryptography` 41.0.7, the last release with a pp38 wheel. A wheel that installs is not proof: import it in the PyPy venv. The fix was to keep `gspread`, the only thing that pulled in cryptography, out of PyPy with a `platform_python_implementation != 'PyPy'` marker. A CPython-only build passing proves nothing about the PyPy step. Build the full image. The CPython step takes about 11 minutes and the PyPy step about 5, and PyPI read timeouts happen, so a scratch harness sets `PIP_DEFAULT_TIMEOUT=300`.

**Why:** each one cost a rerun during WP-0d infra-5 (2026-10-04).
**How to apply:** use these whenever an infra change touches requirements or images. The PyPy item lapses once WP-3b drops PyPy. See [[infra-tooling-traps]].
