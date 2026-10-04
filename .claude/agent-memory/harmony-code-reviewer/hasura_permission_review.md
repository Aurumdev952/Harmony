---
name: hasura-permission-review
description: How to judge Hasura role permissions in Harmony (minimal and complete vs the Relay operations), plus WP-branch-moves-mid-review and legacy venv facts from the WP-0a review
metadata:
  type: project
---

- **Minimality check.** Parse every `web/client/**/__generated__/*.graphql.js` `"text"` with graphql-core (`uv run --with 'graphql-core>=3.2,<4' python <script>` from /tmp, not the repo root: the repo's `graphql/` folder shadows the package) and list root mutation fields per operation. `insert_X`/`update_X`/`delete_X(_by_pk)` give (table, op). Nested inserts and upserts are not in the documents; they live in the JS that builds variables. `grep -rn on_conflict web/client` (non-generated) finds them; in WP-0a all were in `DataUploadApp/AddDataModal/useSelfServeMutation.js`.
- Hasura exposes `on_conflict` to a role only if it has update permission on that table, even with `update_columns: []`. So an upsert target with insert but no update permission breaks the UI at runtime, and static document validation cannot catch it (it is in variables).
- The UI itself writes `id`, `created`, `last_modified` and `data_upload_file_summary.file_path`, so column-scoping insert/update brings little. `file_path` flows into `os.path.join('self_serve', source_id, file_path)` in `self_serve_connection.py`: a pre-existing, client-controlled object-storage key (report to security, WP-5e).
- **Branches move during review.** WP-0a's head moved from 1f6365f to f4db7c1 (infra commits merged) while reviewing, and `mig/integration` moved too. Re-run `git log -3 <branch>` before writing the verdict, name the reviewed SHA, and diff against `git merge-base <head> mig/integration`.
- Legacy proxy tests run in a py3.8 venv: `uv venv --seed -p 3.8 /tmp/x` then its pip with `requirements.txt requirements-web.txt pytest 'bcrypt<4.1'` (a few minutes, run in background). `pip -e git+` drops a `src/` into the cwd, so build from a scratch worktree. For "red on base", copy the test file into a second scratch worktree at the merge base.

**Why:** these took the most time in the WP-0a review (2026-10-04).
**How to apply:** any WP touching `graphql/hasura/**` or the `/api/graphql` proxy, until WP-5e retires Hasura. See also [[review-traps]].
