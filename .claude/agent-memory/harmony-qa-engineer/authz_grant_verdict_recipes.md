---
name: authz-grant-verdict-recipes
description: How QA verified WP-0h (group/role grant checks) live on two private authz stacks, the WP-2b/WP-2c version pairing that works, and CI traps (pylint E1101 on Model.query)
metadata:
  type: reference
---

Learned giving the WP-0h QA verdict (2026-10-04).

- **Stack pairing.** WP-2b's `tests/authz/stack.sh` (f5eea01) expects the *old* WP-2c compose (`git archive 501337e tests/contract/stack`, image `harmony-wp2c-web-server:local`, `--no-build`). The newer WP-2c compose (ff6a529+) needs `CONTRACT_WEB_IMAGE` and generated secrets and fails under the WP-2b script.
- **Two trees, one diff.** `git archive <merge-base>` and `git archive <branch>` into /tmp, add `tests/authz` and the stack to each, `AUTHZ_PROJECT`/`AUTHZ_WEB_PORT` unique per tree, run both. Diff per-test outcomes from `-rA` (strip ` - reason`). With `AUTHZ_BASE_URL` set, `run.sh` without `-m` runs pure + live together.
- **Live probe harness that gave strong evidence:** per probe, snapshot every authz table (`security_group*`, `role`, `role_permissions`, `query_policy_role`, `user_roles`, `user_acl`) through `docker exec <pg> psql -At`, send the request, snapshot again, and count new `Refused grant` lines in `docker logs <web>`. Empty diff = "no state change" proven.
- **Use a fresh actor and fresh role per probe.** On the unfixed tree a successful escalation (H1) makes the actor admin, which silently turns later probes by the same user into superuser probes.
- Group ACL bodies need the full shape (`$uri`, `label`, `resourceType` on resource and resourceRole) or Potion returns 400 "None is not of type 'string'". `POST /api2/dashboard` 500s on the contract stack; insert a `resource` row (type 2) instead.
- **CI pylint gate:** `.github/workflows/integration.yml` runs pylint 2.17.4 on changed files and fails on any error. It flags `Model.query` as E1101 (no-member) in new files; existing code (`managers.py:332`) has the same pattern but is never linted because unchanged. Reproduce with `uv run --no-project -p 3.8 --with-requirements <reqs> --with pylint==2.17.4 python -m pylint -f json <files>` from the tree root (picks up `.pylintrc`).
- Check superuser rows too: validation/deletion fixes change admin outcomes even when the WP's INV-3 table says "superusers unchanged".

Related: [[authz-suite-harness]], [[authz-escalations-found]], [[legacy-flask-verdict-traps]]
