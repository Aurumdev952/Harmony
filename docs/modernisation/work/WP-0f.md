---
wp: "0f"
title: "One CI system, `main` branch, least-privilege Actions"
status: building
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

## Contract changes

None.

## Requests

- [ ] human: confirm that no deployment builds or pushes images with Jenkins from `ci/docker/Jenkinsfile`. Unit 1 deleted it without asking because the human was unavailable. Object before merge and the file comes back from `0c45a48`. Evidence: nothing in the repo references the file (only planning docs and agent instructions name it). It calls eight Makefile targets (`web_client_build`, `web_server_build`, `web_build`, `web_client_push`, `web_server_push`, `web_push`, `etl_pipeline_build`, `etl_pipeline_push`) that no commit of the Makefile has ever defined (`git log -S web_client_build -- Makefile` is empty), so it cannot have run green since it was added on 2023-11-16. `.github/workflows/web.yml` and `pipeline.yml` already build and push the same images.
- [ ] lead: change `COMMIT=${COMMIT:-master}` to `main` in `scripts/lint_python.sh`, `scripts/lint_js.sh` and `scripts/format_python.sh`. These paths have no owning role. `make lint*` and `make black` already pass `COMMIT=main` after unit 2, so only direct calls to the scripts still fail with `fatal: bad revision 'master'`. Blocks nothing in this WP.

## Log

2026-10-04 infra-2 unit 1: delete `ci/docker/Jenkinsfile` and the now-empty `ci/`; check: `grep -rIli jenkins` outside planning docs finds only README's generic mention of task runners and an issue-template option; none of the eight targets it calls match `^<target>[: ]` in the Makefile.
2026-10-04 infra-2 unit 2: Makefile `COMMIT?=main` and help text; check: `make -pn` shows `COMMIT = main`, `grep -c master Makefile` is 0, `make lint-python` now prints "No Python files have changed." where `COMMIT=master` failed with `fatal: bad revision 'master'`.
2026-10-04 infra-2 unit 3: all three workflows pinned by SHA, on `ubuntu-24.04`, `permissions: {}` at the top with per-job grants, no `${{ }}` inside `run:`; check: actionlint 1.7.12 with shellcheck 0.11.0 went from 38 findings to 0, and the YAML assertions and script simulation below pass.

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
- **Left alone (out of scope, noted for later WPs).** Python 3.9 and Node 18.17 in `integration.yml` stay until WP-3 and FE-11 bump them. In the image workflows, `--cache-from "$IMAGE:main,$IMAGE:$TAG"` passes two refs in one flag, which buildx probably reads as a single invalid ref, so the cache likely misses. A `workflow_dispatch` on a branch with `/` in its name gives an invalid image tag. Both behaved this way before this WP. Both belong to WP-3b, which rebuilds the images. There is no Dependabot config to keep SHA pins current. WP-2f should add one for `github-actions`.

## Evidence

- **actionlint baseline vs now.** On `main`: 38 findings (12 `[action]` "runner of actions/checkout@v3 / docker/login-action@v2 / setup-* is too old", 9 `[expression]` "github.head_ref is potentially untrusted", 17 `[shellcheck]` SC2086). On this branch: `actionlint -shellcheck <shellcheck 0.11.0> -oneline` exits 0 with no output. actionlint 1.7.12 is the release binary, checked against the release's `actionlint_1.7.12_checksums.txt` with `sha256sum -c`. shellcheck comes from `shellcheck-py`.
- **YAML parse and policy assertions.** PyYAML 6.0.2 loads all three workflows. Each has top-level `permissions: {}`. Every job has an explicit `permissions` and `runs-on: ubuntu-24.04`. Every `uses:` ref is a 40-hex SHA. No `run:` block contains `${{`. `grep -E 'write-all|ubuntu-latest|ubuntu-22.04'` over `.github/workflows` is empty.
- **Script simulation.** The `run:` blocks of the changed-file, Black, Pylint, eslint and stylelint steps, plus both `prepare` jobs, ran under `bash --noprofile --norc -eo pipefail -c` (the Actions default) with stubbed `gh`, `black`, `pylint`, `eslint` and `stylelint`. With a PR that lists `a.py`, `with space.py`, a deleted `deleted.py`, `web/client/x.jsx`, `web/public/v.js` and `s.scss`, the results were:
  - black got exactly `a.py` and `with space.py`;
  - pylint's convention became `::notice`, and one error failed the step with exit 1;
  - eslint got only `web/client/x.jsx`, and its warning failed the step;
  - stylelint got `s.scss`.

  With only `README.md`, the deleted file and `web/public/v.js`, every lint step printed its "no files" message and exited 0. Both `prepare` jobs mapped `Zenysis`/`Harmony` to `zenysis`/`harmony`.
- **Not verified this session.** No PR run has happened yet: the branch is unpushed. The phase check ("every workflow goes green on a PR") stays open until the PR is opened. The image workflows run only on `push` to `main` and `workflow_dispatch`, so the only way to run them before merge is a manual dispatch. A dispatch on `mig/WP-0f-one-ci-system` would fail at `docker build -t`, because the branch name contains `/` (the pre-existing tag issue above). To exercise them before merge, dispatch from a branch name without a slash. Otherwise the first push to `main` after merge is the first run.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
