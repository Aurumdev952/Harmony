---
name: images-copy-explicit-dirs
description: The web-server and pipeline Dockerfiles COPY an explicit list of top-level dirs, so a new top-level package (harmony/) is missing from images until infra adds it
metadata:
  type: project
---

`docker/web/Dockerfile_web-server` and `docker/pipeline/Dockerfile` copy `config`, `data`, `db`, `log`, `models`, `util`, `web` and so on one by one. The dev image mounts the repo instead. Tests and CI run from the checkout, so they never notice a missing directory.

**Why:** WP-4a (2026-10-05) made `config/__init__.py` import `harmony.core`. Without `COPY harmony`, every image process would fail at `import config` while every suite stayed green. This was routed to infra as a merge-blocking request.

**How to apply:** whenever core code makes a legacy module import a new top-level package, request the Dockerfile COPY lines from infra in the same WP. Check that they landed before the WP closes. Related: [[pipeline-builds-flask-app]].
