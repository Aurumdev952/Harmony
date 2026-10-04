---
name: upstream-artifacts-gone
description: MinIO server images and mc downloads disappeared upstream (2025); where pinned replacements come from and what is still undecided
metadata:
  type: project
---

As of 2026-10-04:
- `minio/minio` is gone from Docker Hub ("repository does not exist") and `quay.io/minio/minio` returns 401. `docker-compose.minio.yaml` cannot be pinned or pulled fresh. A replacement is a human decision (WP-0b request R5).
- `dl.min.io` / `dl.minio.io` mc downloads return **410 Gone**, which broke the pipeline and dev image builds on `main`. `minio/mc` on GitHub is archived, but its releases still download. WP-0b pins `RELEASE.2025-08-13T08-35-41Z` with sha256 checks.
- Resolve tag to digest with `docker buildx imagetools inspect <tag>`, and list tags with digests via the `hub.docker.com/v2/repositories/<ns>/<repo>/tags` API plus `jq`.

**Why:** pinning work assumes upstream artifacts exist. These did not, and nothing in the repo said so.
**How to apply:** before pinning anything MinIO-related, check R5's outcome in `docs/modernisation/work/WP-0b.md`. When a download fails in a build, check for 410 or an archived upstream before assuming a network problem.
