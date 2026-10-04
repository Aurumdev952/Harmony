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

## Log

2026-10-04 infra-2 unit 1: delete `ci/docker/Jenkinsfile` and the now-empty `ci/`; check: `grep -rIli jenkins` outside planning docs finds only README's generic mention of task runners and an issue-template option; none of the eight targets it calls match `^<target>[: ]` in the Makefile.

## Evidence

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | pending | |
| reviewer | pending | |
| security | pending | |
