---
name: cpython313-image-findings
description: Non-obvious facts from moving Harmony's images to CPython 3.13 with uv (ijson C backend gone, non-root upgrade path, Druid stub needs, NodeSource 14 broken, dev venv volume shadowing)
metadata:
  type: project
---

These facts come from WP-3b (2026-10-05). Evidence scripts are in `docs/modernisation/work/WP-3b-evidence/`.

- **ijson.** `db/druid/query_client.py` streams GroupBy responses through `ijson-bigint`. The fork's C backend does not compile on 3.11+, so 3.13 images fall back to pure Python, which parses about 16 times slower. Upstream ijson's C backend and the ctypes `yajl2` backend both fail on Druid's Long.MIN_VALUE, the bug the fork exists for. Keep libyajl out of images, or ijson silently picks the buggy ctypes backend. The fix belongs to core (PERF-7 request in WP-3b).
- **Non-root web image.** Old images ran as root, so existing hosts have root-owned `${DATA_PATH}/output` (static files, logs) and uploads. They also mount the mc config at `/root/.mc`. `docker/web/run_as_zenysis.sh` starts as root, chowns only those paths, copies the mc config, then `setpriv`s to uid 1000. celery beat needs `--schedule=/tmp/...`, because the working directory is read-only to the app user.
- **Running the prod image on a stack** needs a Druid stub that lists a datasource (reuse `tests/contract/stack/druid_stub.py` from WP-2c) and `ZEN_OFFLINE=1`. Otherwise production startup force-populates dimension metadata from the stub and fails with an IntegrityError.
- **Dev image.** NodeSource's `setup_14.x` repository fails signature checks (`NO_PUBKEY 1655A0AB68576280`), so the dev image did not build on main. It now takes Node 18.17.1 from nodejs.org by checksum. node-gyp needs some `python3` on PATH for node-pty, so jammy's python3 is installed. Docker fills a named volume from the image only while the volume is empty, which is why the dev venv volume was renamed (`web_venv_cp313`).
- **Rootless Docker** on the build host: files the host user owns appear root-owned in containers. That is a cheap way to simulate an old root-written host.

**Why:** none of this is visible from the Dockerfiles, and each item cost a rerun.
**How to apply:** use this for any image, Compose or pipeline-performance work after WP-3b, and when reviewing core's ijson change. See [[image-verification-recipes]] and [[compose-testing-traps]].
