---
name: uv-build-deps-not-locked
description: uv.lock does not pin sdist build backends (setuptools, cython, cffi...); how to prove it and the fix to require
metadata:
  type: project
---

`uv sync --locked` installs runtime packages from uv.lock with hashes, but the PEP 517 build
environments for sdists and git sources are resolved at sync time from PyPI (latest compatible,
no lock, no hash). Found in WP-2f (2026-10-04): 29 source builds on CPython 3.9, build envs got
setuptools 82.0.1, pytest-runner 6.0.1, cython 3.3.0, cffi 2.0.0, greenlet 3.2.5, pycparser 2.23,
none of them in uv.lock. The old pip CI used `--no-build-isolation`, so this is new exposure.

**Why:** SEC-9 asks for pinning "where possible", and uv has a mechanism:
`[tool.uv] build-constraint-dependencies = [...]`. uv records it in the lock `[manifest]` as
`build-constraints`, so `--locked` enforces it (verified on uv 0.12.5). It pins versions, not hashes.

**How to apply:** on any WP that adds or changes uv.lock, prove it with a fresh cache:
`UV_CACHE_DIR=/tmp/x UV_PROJECT_ENVIRONMENT=/tmp/v uv sync --project <wt> --locked -v` and grep
`Installing in .* in /tmp/x/builds` for the build requirements. A shared cache hides the builds.
DNS errors at high concurrency are common here; set `UV_HTTP_RETRIES=8 UV_CONCURRENT_DOWNLOADS=6`.
Related: [[ci-review-toolbox]].
