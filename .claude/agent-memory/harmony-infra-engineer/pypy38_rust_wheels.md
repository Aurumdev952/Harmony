---
name: pypy38-rust-wheels
description: Pipeline image PyPy is jammy's 3.8 (7.3.9); Rust-extension deps (pydantic-core) have no pp38 wheel and need a builder stage
metadata:
  type: project
---

The pipeline image (`docker/pipeline/Dockerfile`) installs PyPy from jammy apt, which gives PyPy 7.3.9 on Python 3.8. The dev image instead uses PyPy 3.9 (v7.3.11 tarball). Most Rust-built packages publish PyPy wheels for 3.9 and later only. pydantic-core 2.27.2 is one of them. In the image, pip falls back to the sdist and fails with `No module named 'maturin'`. On a host the same install passes, because uv uses the host's cargo. So a green local "PyPy 3.8" check proves nothing about the image.

**Why:** WP-4a added pydantic. Its pipeline image build broke even though core reported that PyPy 3.8 passed (2026-10-05).

**How to apply:** when a WP adds a dependency with a compiled extension, build the pipeline image itself (or check PyPI for a `pp38` wheel). The fix pattern is the `pypy-wheels` stage: a pinned `rust:` image, then `pip wheel` under jammy pypy3, then `--find-links` in the PyPy install. `tests/infra/test_dockerfiles.py` ties `PYDANTIC_CORE_VERSION` to `uv.lock`. WP-3b (Python 3.13) should delete the stage. Complements [[image-verification-recipes]] (gspread marker, the alternative when a dependency can stay off PyPy).
