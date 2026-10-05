---
name: cpython313-image-findings
description: Non-obvious facts from moving Harmony's images to CPython 3.13 with uv (Druid JSON parser, timing noise, non-root upgrade path, Druid stub needs, NodeSource 14 broken, dev venv volume shadowing)
metadata:
  type: project
---

These facts come from WP-3b (2026-10-05). Evidence scripts are in `docs/modernisation/work/WP-3b-evidence/`.

- **Druid JSON parsing.** `ijson-bigint`'s C backend does not compile on 3.11+, and upstream ijson's C and ctypes `yajl2` backends both fail on Druid's Long.MIN_VALUE. Core replaced ijson with the stdlib streamer `db/druid/json_stream.py` (WP-3b). Images install no JSON stream parser, and libyajl stays out. Parse timings on the shared build host swing 3 to 4 times with load (load 45 on 16 cores is normal there). Compare an image against the host environment interleaved in one run before blaming the image. PERF-7 is judged by decision 0011's paired A/B gate.
- **`uv pip check` catches dead backports.** The `dataclasses` 3.6 backport sat in the pipeline group until WP-3b. `tests/infra/test_pyproject_pins.py` now runs `uv pip check` over the locked environment.
- **Non-root web image.** Old images ran as root, so existing hosts have root-owned `${DATA_PATH}/output` (static files, logs) and uploads. They also mount the mc config at `/root/.mc`. `docker/web/run_as_zenysis.sh` starts as root, chowns only those paths, copies the mc config, then `setpriv`s to uid 1000. celery beat needs `--schedule=/tmp/...`, because the working directory is read-only to the app user.
- **Running the prod image on a stack** needs a Druid stub that lists a datasource (reuse `tests/contract/stack/druid_stub.py` from WP-2c) and `ZEN_OFFLINE=1`. Otherwise production startup force-populates dimension metadata from the stub and fails with an IntegrityError.
- **Dev image.** NodeSource's `setup_14.x` repository fails signature checks (`NO_PUBKEY 1655A0AB68576280`), so the dev image did not build on main. It now takes Node 18.17.1 from nodejs.org by checksum. node-gyp needs some `python3` on PATH for node-pty, so jammy's python3 is installed. Docker fills a named volume from the image only while the volume is empty, which is why the dev venv volume was renamed (`web_venv_cp313`).
- **Rootless Docker** on the build host: files the host user owns appear root-owned in containers. That is a cheap way to simulate an old root-written host.

**Why:** none of this is visible from the Dockerfiles, and each item cost a rerun.
**How to apply:** use this for any image, Compose or pipeline-performance work after WP-3b, and when judging parse or pipeline timings. See [[image-verification-recipes]] and [[compose-testing-traps]].
