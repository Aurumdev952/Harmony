---
name: wp-0f-open-items
description: Docker Hub zengineering path removed in WP-0f pending human confirmation; slash-in-branch image tag bug fixed in WP-3b; --cache-from comma form is correct
metadata:
  type: project
---

WP-0f removed the whole Docker Hub `zengineering` image path without the human's confirmation, because the human was unavailable. That path was the Jenkinsfile plus the hyphenated Makefile `*-build`, `*-push` and `all-push` targets. The human can object before merge.

The `zengineering/harmony-*` images on Docker Hub were last updated on 2023-11-16. README (lead-owned) still points deployers at them; a request is open in WP-0f.

The image-workflow tag defect (`github.head_ref || github.ref_name` breaks on branch names containing `/`) was fixed in WP-3b unit 6: `prepare` emits a sanitised `image_tag`.

`--cache-from "a:main,a:tag"` is NOT a bug. buildx splits a comma-separated value without `=` into one registry entry per ref, and this was reproduced locally. Do not "fix" it.

**Why:** nobody can run the image workflows before merge, so these facts are easy to "fix" wrongly.

**How to apply:** before relying on the Docker Hub removal, check the Requests section of `docs/modernisation/work/WP-0f.md` for the human's answer. Related: [[ci-tooling-and-guards]].
