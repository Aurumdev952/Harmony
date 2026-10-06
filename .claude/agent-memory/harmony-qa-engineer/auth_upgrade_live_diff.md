---
name: auth-upgrade-live-diff
description: How QA proved the WP-3d Flask 2.3 / jwt-extended 4 upgrade live - same probe matrix against a base and a branch contract stack, old-library minting, in-container render tokens, browser redirect chains
metadata:
  type: reference
---

Recipe from the WP-3d QA gate (2026-10-06). It took about 1.5 hours under heavy host load.

- **Before and after on live stacks.** Run one probe script against a base stack and then against a branch stack, one stack at a time, and diff the two JSON outputs. Only the intended changes should differ. For WP-3d these were the token layout, relative `Location` headers that resolve to the same URLs, and INV-3 rows 15 and 17. This is stronger than the builder's one-sided statuses.
- **Base stack without git.** Run `git archive <base>` into /tmp and extract it. `stack.sh` needs no git, so it runs from the extracted tree. Use a copy of `stack.sh` with `--network host` on the build, and delete the copy after.
- **Old-library tokens.** Run `UV_PROJECT_ENVIRONMENT=/tmp/x-venv uv run --locked` in the extracted base tree. Call the production minting paths (`create_user_access_token`, `APIToken.generate_token` with `generate_id` patched to the id of a row the live stack issued) with the stack's `JWT_SECRET_KEY`, taken from the secrets file. Call the minter from the probe through `subprocess`. Write tokens only to files with mode 600.
- **Old Flask-Login sessions.** Under the old venv, call `login_user` in a `test_request_context` and serialise with `app.session_interface.save_session` using the stack's `DEFAULT_SECRET_KEY`. As a control, sign a cookie with the same signer that uses the `_user_id` key.
- **Checking that needs are read.** Send an old-layout API token to the Hasura proxy (`POST /api/graphql` requires `'*'` in `needs`) and to `/admin`. A control token with the same row id and `needs: []` must be refused.
- **Render tokens live.** Pipe a script into `docker exec -i <web> python -`. The script builds `create_bare_app` plus `initialize_jwt_manager` and `initialize_cache`, which gives the real Redis cache. Inside `render_token(...)`, call gunicorn at 127.0.0.1:5000 in the same container. Check the token while the render is live, after it is spent, and with a stale policy.
- **Browser.** The logout URL is `/user/sign-out`, not `/logout`. The only server-side redirect after a save is Flask-User's `/user/change-password`: POST returns 302 to `/`, which returns 302 to `/overview`. Record redirect chains with `request.redirectedFrom()` in `browser_run_code_unsafe`. Serve client bundles with the qa-0j assets sidecar (`--network container:<web>`); 404s for fonts and images under `/build/min` come from the sidecar, not the app.
- **Traps.**
  - `POST /api2/dashboard` rejects a `legacy` key.
  - Keep probe scratch files out of the tree mounted into the stack.
  - A cached stack build can reuse a tag that another agent built. Check `CreatedAt` before removing an image "you built".

Related: [[reference-contract-stack]], [[legacy-stack-browser-verify]], [[worktree-guard-bash]].
