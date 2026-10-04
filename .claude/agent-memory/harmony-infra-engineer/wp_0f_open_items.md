---
name: wp-0f-open-items
description: Pre-existing CI defects WP-0f deliberately left for WP-3b/WP-2f, and the Jenkinsfile deletion awaiting human confirmation
metadata:
  type: project
---

WP-0f deleted `ci/docker/Jenkinsfile` without the human's confirmation, because the human was unavailable. It can be restored from commit `0c45a48` if the human objects before merge.

WP-0f also left these defects in the image workflows (`web.yml`, `pipeline.yml`):
- `--cache-from "$IMAGE:main,$IMAGE:$TAG"` puts two refs in one flag, so the cache probably misses.
- The tag `github.head_ref || github.ref_name` breaks on branch names that contain `/`, which includes every `mig/WP-*` branch.

**Why:** they were out of scope for "one CI system, least privilege", and nobody can run the image workflows before merge.

**How to apply:** fix both in WP-3b when the images are rebuilt. Use one `--cache-from` per ref, and sanitise the tag (for example, replace `/` with `-`). Before relying on the Jenkins deletion, check the Requests section of `docs/modernisation/work/WP-0f.md` for the human's answer. Related: [[ci-tooling-and-guards]].
