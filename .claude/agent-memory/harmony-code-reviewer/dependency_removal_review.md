---
name: dependency-removal-review
description: How to review dead-code and dependency-removal WPs; checks that found real defects on WP-0d that the builders' own greps missed
metadata:
  type: project
---

Builders' "dead" proofs grep module and class names. They miss URL-string callers and transitive effects. Check these yourself.

**Why:** on WP-0d (2026-10-04) every instance's grep passed. Still, `scripts/db/graphql/sync_schema.sh` introspected the deleted Flask `/graphql` URL, and `graphql/v2/schema.graphql` plus the `relay-web` script in package.json were artifacts of the deleted `web/server/graphql/filters.py`. Removing graphene also lifted its `aniso8601<=7` cap: 7.0.0 became 10.0.1 under Potion's DateString and DateTimeString converters, and nobody recorded it.

**How to apply:**
- **Deleted routes:** grep the URL itself (`/graphql`, `host:port/graphql`) across every file type, including `scripts/**` shell scripts and generated schema snapshots, not only `*.py` imports.
- **Removed requirements:** prepare base and trimmed copies of the requirement files, rewriting each `-e <url>#egg=X` line to `X @ <url>`. Then run `uv pip compile --python-version 3.8` (3.9 for the dev and CI set, because pytest-httpx needs it) and diff the resolved sets.
  - The "gone" list is the set of transitive packages to grep for importers.
  - The "changed" list shows caps that were lifted. Probe any changed package that sits on an API boundary.
- **New pins with a `== 'PyPy'` marker:** WP-3b's phase text says "delete the PyPy markers". Stripping the marker from such a line turns it into a CPython pin. Make sure the WP records that the line must be deleted, not de-markered.
- **WP-2f:** it generates `requirements*.txt` from pyproject.toml and deletes mypy.ini. Any WP touching those files must record which of the two ports the change, and the port must include added pins as well as removals.
- **Big evidence:** check for byte-identical evidence files (`md5sum | uniq -w32 -D`). Prefer committed scripts plus diffs over raw sweep TSVs.

Related: [[review-env-traps]]
