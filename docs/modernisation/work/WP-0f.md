---
wp: "0f"
title: "One CI system, `main` branch, least-privilege Actions"
status: review
owner_role: "infra"
instances:
  - name: "infra-2"
    files:
      - ci/**
      - .github/workflows/**
      - Makefile
branch: "mig/WP-0f-one-ci-system"
requirements: [SEC-9]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-0f: One CI system, `main` branch, least-privilege Actions

Phase detail: `docs/modernisation/phase-0-security-and-subtraction.md` section 0f. SEC-9 is covered here only for GitHub Actions; images and downloads are WP-0b, dependencies WP-2f.

## Plan

Units, in order. Each line names the change and the check that ends it.

1. Delete `ci/docker/Jenkinsfile`. Check: `grep -rIi jenkins` finds no file that references it, and none of the Makefile targets it calls exist.
2. Makefile defaults to `main`: `COMMIT?=main` and help text. Check: `make -pn` shows `COMMIT = main`; `make help` renders.
3. Workflows: pin every action by commit SHA at its current major (tag in a comment), pin `runs-on: ubuntu-24.04`, set `permissions: {}` at workflow level and per-job least privilege, and pass untrusted context (`head_ref`, `ref_name`) through `env` instead of inline `${{ }}` in scripts. Check: `actionlint` (with shellcheck) reports zero findings; every workflow parses as YAML; no `write-all`, `ubuntu-latest`, `ubuntu-22.04` or tag-only `uses:` remain.
4. Review fixes:
   - Scope `GH_TOKEN` and `PR_NUMBER` to the "List changed files" steps.
   - Remove the Makefile's Docker Hub `zengineering` image targets and defaults, in favour of `make build` and a new `make push`, both through `docker-compose.build.yaml`.
   - Correct the `--cache-from` and default-shell claims.

   Check:
   - actionlint reports 0;
   - the policy script asserts no job-level `GH_TOKEN`;
   - the simulation shows the linters cannot see the token;
   - `make -n push` and `docker compose -f docker-compose.build.yaml config --images` show `ghcr.io/zenysis`.

## Contract changes

None.

## Requests

- [ ] human: confirm that nothing still builds or pulls images through the Docker Hub `zengineering` path. Units 1 and 4 removed that path without asking, because the human was unavailable. Object before merge and both can be restored from `0c45a48` (Jenkinsfile) and `d180d75` (Makefile targets). The evidence:
  - **Where the Jenkinsfile pushed.** The deleted `ci/docker/Jenkinsfile` pushed to Docker Hub `zengineering`, through `docker login` with the Jenkins credential `docker-io-credentials` (its lines 21 and 39). It did not push to ghcr.io, where `.github/workflows/web.yml` and `pipeline.yml` push.
  - **Targets it called.** It called underscore targets (`web_client_build`, ..., `etl_pipeline_push`), and no commit of the Makefile has ever defined those (`git log -S web_client_build -- Makefile` is empty). Hyphenated equivalents (`web-client-build`, ..., `all-push`) did exist, with `DOCKER_NAMESPACE?=zengineering`. So the Jenkinsfile as committed could not run. Someone may have run the hyphenated targets by hand.
  - **When the images last changed.** The Docker Hub API (`hub.docker.com/v2/repositories/zengineering/`) shows `harmony-web`, `harmony-web-client`, `harmony-web-server` and `harmony-etl-pipeline` last updated on 2023-11-16, the day the Jenkinsfile was added, and never since.
  - **Retiring the Jenkins credential.** If Jenkins still holds `docker-io-credentials`, retire it (security note).
- [ ] lead: update README.md. Line 390 tells deployers to set `DOCKER_NAMESPACE=zengineering`, which makes `docker-compose.yaml` pull images frozen on 2023-11-16. Line 429 points "pre-built images" at hub.docker.com/zengineering. Change them to `ghcr.io/zenysis`, the compose default and the namespace CI pushes to, or drop the line so the default applies. Under "Custom Builds", mention `make push`. README is lead-owned. This is deferred from this WP and blocks nothing in it.

## Log

2026-10-04 infra-2 unit 1: delete `ci/docker/Jenkinsfile` and the now-empty `ci/`; check: `grep -rIli jenkins` outside planning docs finds only README's generic mention of task runners and an issue-template option; none of the eight targets it calls match `^<target>[: ]` in the Makefile.
2026-10-04 infra-2 unit 2: Makefile `COMMIT?=main` and help text; check: `make -pn` shows `COMMIT = main`, `grep -c master Makefile` is 0, `make lint-python` now prints "No Python files have changed." where `COMMIT=master` failed with `fatal: bad revision 'master'`.
2026-10-04 infra-2 unit 3: all three workflows pinned by SHA, on `ubuntu-24.04`, `permissions: {}` at the top with per-job grants, no `${{ }}` inside `run:`; check: actionlint 1.7.12 with shellcheck 0.11.0 went from 38 findings to 0, and the YAML assertions and script simulation below pass.
2026-10-04 infra-2 unit 4 (reviewer changes): `GH_TOKEN` and `PR_NUMBER` step-scoped; Docker Hub Makefile targets and defaults replaced by `make push`; Jenkins evidence amended; `--cache-from` and default-shell claims corrected; merged `mig/integration`, which carries the lead's `main` default for the lint scripts, so that request is dropped. Check: actionlint 0, policy OK, simulation shows no token for linters, `make -n push` targets ghcr.io/zenysis.

## Decisions

- **Action majors.** The phase says v4/v5, which were current when it was written. On 2026-10-04 the current releases are checkout v7.0.1, setup-python v7.0.0, setup-node v7.0.0, cache v6.1.0 and docker/login-action v4.6.0. v4/v5 of the `actions/*` set still run on the deprecated Node 20 runtime, so this WP takes the current majors. Their release notes list no input changes that these workflows use. setup-python v7 still ships CPython 3.9.25 for ubuntu-24.04 (checked in `actions/python-versions` `versions-manifest.json`).
- **Pinning.** Every `uses:` is a full commit SHA with the tag in a trailing comment (SEC-9, `harmony-infra` CI rules). Tags were resolved with `gh api repos/<action>/commits/<tag> --jq .sha`.
- **Permissions.**

  | Workflow / job | Grant | Why |
  |---|---|---|
  | integration `lint-python`, `lint-js` | `contents: read`, `pull-requests: read` | checkout, and `gh pr view` to list the changed files |
  | web, pipeline `prepare` | none | lowercases two context values |
  | web `build-web-*`, pipeline `build-etl-pipeline` | `contents: read`, `packages: write` | checkout, push to ghcr.io |

  `actions/cache` authenticates with the runner's cache token, not `GITHUB_TOKEN`, so it needs no grant. Every checkout sets `persist-credentials: false`. No step after checkout uses git credentials (`gh` reads `GH_TOKEN`, `docker/login-action` takes its own password).
- **Script injection.** `github.head_ref` and `github.ref_name` reached shell scripts through inline `${{ }}`, which actionlint flags. They now arrive through `env:`. The integration jobs use the PR number, not the head branch name, to call `gh pr view`. While fixing shellcheck's SC2086 findings, the changed-file lists became bash arrays. `xargs sh -c '[ -e "{}" ]'` spliced PR-controlled filenames into a shell string. A `while read` loop replaces it. The PR's file list is fetched once per job instead of once per step.
- **Token scope.** `GH_TOKEN` and `PR_NUMBER` are set only on the two "List changed files" steps, so `pip install`, `yarn install` and the linters run without the token.
- **Docker Hub image targets removed.** Removed from the Makefile:
  - `DOCKER_NAMESPACE?=zengineering` and `DOCKER_TAG?=latest`;
  - the targets `web-client-build`, `web-client-push`, `web-server-build`, `web-server-push`, `web-build`, `web-push`, `etl-pipeline-build`, `etl-pipeline-push`, `all-build` and `all-push`.

  They duplicated `make build` (`docker-compose.build.yaml`), whose namespace already defaults to `ghcr.io/zenysis`. `make web-build` was also broken: it never passed `IMAGE_PREFIX`, so `docker/web/Dockerfile_web` resolved `FROM zengineering/-web-client:latest`.

  A new `make push` pushes `web-client web-server web etl-pipeline`, or `$(SERVICE)`, through the same compose file. It honours `DOCKER_NAMESPACE`, `DOCKER_IMAGE_PREFIX` and `DOCKER_TAG` from `.env`. The local-only `dev` image is not pushed.

  I removed the targets rather than retargeting them, because CI (`web.yml`, `pipeline.yml`) is the one system that publishes images. Deployers building their own images keep `make build` plus `make push`.
- **`--cache-from` (correction).** An earlier draft said `--cache-from "$IMAGE:main,$IMAGE:$TAG"` was a single invalid ref. That was wrong. buildx's `ParseCacheEntry` splits a comma-separated value without `=` into one registry entry per field, so both refs are imported. Reproduced locally: `docker build --cache-from "a:main,b:tag"` logs a separate `importing cache manifest from` line for each. WP-3b must not "fix" this flag.
- **Left alone (out of scope, noted for later WPs).**
  - Python 3.9 and Node 18.17 in `integration.yml` stay until WP-3 and FE-11 bump them.
  - In the image workflows, a `workflow_dispatch` on a branch with `/` in its name gives an invalid image tag. That was true before this WP too, and it belongs to WP-3b.
  - There is no Dependabot config to keep SHA pins current. WP-2f should add one for `github-actions`.

## Evidence

- **actionlint baseline vs now.** On `main`: 38 findings (12 `[action]` "runner of actions/checkout@v3 / docker/login-action@v2 / setup-* is too old", 9 `[expression]` "github.head_ref is potentially untrusted", 17 `[shellcheck]` SC2086). On this branch: `actionlint -shellcheck <shellcheck 0.11.0> -oneline` exits 0 with no output. actionlint 1.7.12 is the release binary, checked against the release's `actionlint_1.7.12_checksums.txt` with `sha256sum -c`. shellcheck comes from `shellcheck-py`.
- **YAML parse and policy assertions.** PyYAML 6.0.2 loads all three workflows. Each has top-level `permissions: {}`. Every job has an explicit `permissions` and `runs-on: ubuntu-24.04`. Every `uses:` ref is a 40-hex SHA. No `run:` block contains `${{`. `grep -E 'write-all|ubuntu-latest|ubuntu-22.04'` over `.github/workflows` is empty.
- **Script simulation.** The `run:` blocks of the changed-file, Black, Pylint, eslint and stylelint steps, plus both `prepare` jobs, ran under `bash -e -c`, which is the Actions default shell `bash -e {0}` when `shell:` is unset. An earlier draft wrongly called `bash --noprofile --norc -eo pipefail` the default; that is what `shell: bash` gives. The steps ran with stubbed `gh`, `black`, `pylint`, `eslint` and `stylelint`. With a PR that lists `a.py`, `with space.py`, a deleted `deleted.py`, `web/client/x.jsx`, `web/public/v.js` and `s.scss`, the results were:
  - black got exactly `a.py` and `with space.py`;
  - pylint's convention became `::notice`, and one error failed the step with exit 1;
  - eslint got only `web/client/x.jsx`, and its warning failed the step;
  - stylelint got `s.scss`.

  With only `README.md`, the deleted file and `web/public/v.js`, every lint step printed its "no files" message and exited 0. Both `prepare` jobs mapped `Zenysis`/`Harmony` to `zenysis`/`harmony`.

  After unit 4, each step gets only its own `env:`. The `gh` stub exits 4 without `GH_TOKEN`, and it succeeded in both "List changed files" steps. The `black` stub printed `GH_TOKEN visible to linter: no`.
- **Unit 4 policy check.** In addition to the assertions above, the policy script (`/tmp/wp0f-sim/policy.py`) asserts no workflow-level or job-level `env` carries `GH_TOKEN`, and only steps named "List changed files" set it. Result: `policy OK`. actionlint with shellcheck still exits 0.
- **Unit 4 Makefile.**
  - `make -n push` prints `docker compose --env-file /dev/null -f docker-compose.build.yaml push web-client web-server web etl-pipeline`.
  - `make -n push SERVICE=web` pushes only `web`.
  - `docker compose -f docker-compose.build.yaml config --quiet` passes.
  - `config --images` lists `ghcr.io/zenysis/harmony-{web-client,web-server,web,etl-pipeline}:latest` plus the local `harmony-dev-web:latest`, which `make push` does not push.
  - `make help` shows `push`.
  - Before the change, `make -n web-build` printed a build with `--build-arg NAMESPACE=zengineering` and no `IMAGE_PREFIX`.
- **Not verified this session.** No PR run has happened yet: the branch is unpushed. The phase check ("every workflow goes green on a PR") stays open until the PR is opened. The image workflows run only on `push` to `main` and `workflow_dispatch`, so the only way to run them before merge is a manual dispatch. A dispatch on `mig/WP-0f-one-ci-system` would fail at `docker build -t`, because the branch name contains `/` (the pre-existing tag issue above). To exercise them before merge, dispatch from a branch name without a slash. Otherwise the first push to `main` after merge is the first run.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 qa-0f: actionlint 38 to 0 reproduced; SHA pins, permissions, Makefile and hostile-filename simulation verified. PR run of integration.yml deferred until push; human to confirm Jenkinsfile. |
| reviewer | changes-requested | 2026-10-04 rev-0f: pins, runners, permissions and env indirection correct. Fix: scope GH_TOKEN/PR_NUMBER to the list-changed-files steps; amend the Jenkins evidence (Docker Hub zengineering vs ghcr, README:390,429, hyphenated Makefile push targets, Hub images last pushed 2023-11-16); correct the false --cache-from and default-shell claims in WP and memory. |
| security | approved | 2026-10-04 sec-0f: SHA pins match tags and are signed upstream heads; zizmor 100 to 0, actionlint 38 to 0; least-privilege per job; no untrusted interpolation; nothing to rotate. Low: scope GH_TOKEN to the two list-changed-files steps (WP-2f); mutable :latest deploy tag (WP-0b/3b); retire any old Jenkins docker-io-credentials. |
