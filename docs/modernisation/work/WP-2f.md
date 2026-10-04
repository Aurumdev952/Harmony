---
wp: "2f"
title: "uv, ruff, mypy, CI running every suite"
status: review
owner_role: "infra"
instances:
  - name: "infra-2"
    files:
      - pyproject.toml
      - uv.lock
      - requirements*.txt
      - mypy.ini
      - .pylintrc
      - .dockerignore
      - docker/export_requirements.py
      - ci/**
      - tests/infra/conftest.py
      - tests/infra/test_requirements_export.py
      - tests/toolchain/**
      - .github/workflows/integration.yml
      - .github/dependabot.yml
      - Makefile
branch: "mig/WP-2f-uv-ruff-mypy-ci"
requirements: [SEC-9, QA-4, INV-8]
contracts_consumed: []
contracts_changed: []
security_review: true
---

# WP-2f: uv, ruff, mypy, CI running every suite

Phase detail: `docs/modernisation/phase-2-test-harness-and-toolchain.md` section 2f. Branched from `mig/integration`. The starting point is WP-2a's minimal `pyproject.toml` (`mig/WP-2a-golden-query-suite`).

## Plan

Units, in order. Each line names the change and the check that ends it.

1. **`pyproject.toml` and `uv.lock` become the source of truth for Python dependencies.**
   - `requirements.txt` becomes `[project].dependencies`.
   - `requirements-web.txt`, `requirements-pipeline.txt` and `requirements-dev.txt` become the dependency groups `web`, `pipeline` and `dev`.
   - Today's pins are kept as they are.
   - The lock is for CPython 3.9, the CI and dev interpreter. Moving to 3.13 means changing `requires-python` and re-locking (WP-3b).

   Check:
   - `uv lock` succeeds, and `uv sync --locked` builds the environment;
   - `uv run pytest` passes;
   - WP-2a's golden suite passes under this environment.
2. **`requirements*.txt` are generated from `pyproject.toml`** by `docker/export_requirements.py` (`make requirements`). The images keep `pip install -r` until WP-3b switches them to uv. Check:
   - every generated file has the same set of requirement lines as today's hand-written file, so the image inputs do not change;
   - `tests/infra/test_requirements_export.py` fails when they drift.
3. **ruff replaces black and pylint.**
   - Configuration lives in `pyproject.toml`.
   - Formatting matches black: line length 88, quote style preserved.
   - Lint runs repo-wide with a rule set the tree passes today.
   - `.pylintrc` is deleted, and black and pylint leave the `dev` group.
   - The Makefile lint targets call ruff.

   Check: `uv run ruff check .` exits 0, and `ruff format --check` passes on a file that black accepted.
4. **mypy configuration moves into `pyproject.toml`** (`mypy.ini` is deleted), with the same files, plugin and per-module overrides. Check: `uv run mypy` gives the same result as `mypy --config-file mypy.ini` before the move.
5. **`integration.yml` runs the toolchain on every PR:**
   - `uv lock --check` and `uv sync --locked`;
   - `ruff check`, and `ruff format --check` on changed files;
   - mypy;
   - `pytest` over `tests/`, so new suites run without a workflow change. Suites that need the compose stack are marked `stack` and deselected.

   Every action is pinned by SHA, and every grant follows WP-0f. Check:
   - actionlint reports 0;
   - the WP-0f policy script passes;
   - the job's commands pass locally;
   - a deliberately broken test makes the pytest command exit non-zero.
6. **Dependabot** covers `github-actions` and `uv`. Check: `check-jsonschema --builtin-schema vendor.dependabot` passes.
7. **Review fixes, and the WP-2c and WP-2d suites:**
   - locked build tools;
   - the dependencies and CI tools those suites need;
   - a merge-base lint;
   - a hardened exporter;
   - per-job caches and a concurrency group;
   - Dependabot cooldown;
   - ruff S rules.

   Check: fresh-cache `uv sync --locked -v`, then every suite with 2a, 2c and 2d present, with one broken case per suite, plus actionlint and zizmor.

## Contract changes

None.

## Requests

None of these blocks this WP.

### Answers to other WPs' requests (SPEC 7.3)

- [x] **WP-2c (`infra: add pytest, hypothesis, jsonschema and requests to the dev group`).** Done in unit 7:
  - `hypothesis==6.91.0` and `jsonschema==4.17.3` are now direct pins in `dev`. hypothesis 6.92+ needs `attrs>=22.2`, and attrs is pinned at 21.4.0.
  - `pytest` and `requests==2.28.1` were already locked.

  Offline, the contract suite runs in the 3.9 job: 540 tests collected. The replay test needs no `stack` marker to keep CI green, because its `contract_runner` fixture skips when `CONTRACT_BASE_URL` is unset (166 skips). The earlier claim that unmarked stack tests "turn every PR red" was wrong and is withdrawn.
- [x] **WP-2d (`tests/pipeline` dependencies and tools).**
  - Every pin in `tests/pipeline/requirements.txt` is in `uv.lock`, at the same pin where one is given: pylib (same commit), python-slugify, `unidecode==1.1.1`, python-dateutil, related, `attrs==21.4.0`, six, `future==0.18.3`, contextlib2 (21.6.0), pytest, and hypothesis (now pinned).
  - The 3.9 job installs `lz4` and `pigz` with apt-get before pytest.
  - The steps run as subprocesses with `sys.executable`, so they get the locked 3.9 environment.
- [ ] **Contract stack replay job: infra-2.** It is a follow-up unit of this WP, added once WP-2c and WP-0b (for the bcrypt pin its stack image needs) are on `mig/integration`. It cannot be tested before `tests/contract/stack/stack.sh` exists on the base. It has to land before phase 5 starts, because QA-2 needs the replay on every PR for 5*.
- [x] **Pipeline suite job: infra-2, in this WP.** No separate job is needed: `tests/pipeline` runs in the 3.9 job (Evidence, unit 7). `PIPELINE_FIXTURE_PYTHON=pypy3.9` stays a local option; PyPy goes in WP-8d.

### Merge-order items

- [x] **WP-2a** (merged into `mig/integration` at `ab4e2f7`, and here in `e7363e7`). I took WP-2f's `pyproject.toml` and `uv.lock`, dropping WP-2a's `golden` group and `testpaths = ["tests/golden"]`. Every package in the `golden` group is in WP-2f's dependencies under the same normalised name. Results:
  - `uv run --locked pytest tests/golden`: 269 passed;
  - `uv run --locked python tests/golden/record.py --check`: "85 cases, 0 fixture files would change", exit 0.
- [ ] **WP-0b, when it lands on `mig/integration`:**
  - move `bcrypt==4.0.1` from `requirements.txt` into `[project].dependencies` next to flask-user, then `uv lock` (today's lock resolves bcrypt 5.0.0) and `make requirements`. Its `requirements.txt` edit would otherwise fail the drift test. Until then the lock stays as it is;
  - `tests/infra/test_requirements.py` reads the generated `requirements.txt` in the 3.13 lane, so it keeps working;
  - `tests/core`, `tests/web` and `tests/druid_setup` join the 3.9 job automatically. Re-run the full local CI on that merge, and mark anything that needs the stack `stack`.
- [ ] **WP-0d (`mig/WP-0d-dead-backend-code`, with its infra side branch), whichever merges second.** Port:
  - the removed packages out of `pyproject.toml` (`[project].dependencies`, `web`, `pipeline`, `dev`), then `uv lock` and `make requirements`;
  - the five removed mypy overrides (`flask_admin`, `flask_graphql`, `graphene`, `graphene_sqlalchemy`, `graphql_relay`) out of `[[tool.mypy.overrides]]`;
  - **the gspread PyPy marker, not a pin.** WP-0d has no cryptography line any more. It changes gspread to `gspread>=5.4.0 ; platform_python_implementation != 'PyPy'`. Nothing imports gspread, and under PyPy it pulls in cryptography, which aborts PyPy on import. So in `[project].dependencies`, `"gspread>=5.4.0"` becomes that marked line, followed by `uv lock` and `make requirements`. `make requirements` must never export an unmarked gspread, or the etl-pipeline image's PyPy step builds cryptography from source and fails. The pin test strips markers before matching, so its allowlist stays as it is.
- [ ] **In-flight branches, after rebasing onto this WP.** Before WP-2f, pylint failed CI only on `type == error`, so unused imports (F401) and formatting passed unless black objected. Now ruff fails CI on F401 and on any unformatted changed file. Each in-flight branch owner runs `make format-python COMMIT=<base>` and turns intentional imports into `# noqa: F401`. Known today:
  - WP-0c (backend side): 2 F401 and 4 files to reformat (reviewer's count);
  - WP-0b: 2 F401 and 2 to reformat (reviewer's count);
  - WP-2a: `tests/golden` (4 files to reformat);
  - WP-2c: its test files;
  - `mig/integration` against `main`: `scripts/create_user.py` (5 F401 model-registration imports that need `# noqa: F401`, 1 E711, and a reformat) and `scripts/agents/{check_team,ownership,task_gate}.py` (reformat), owned by the lead.

  `ci/lint_python.sh main` lists all of these.

- [x] **WP-0a and WP-0c** (on `mig/integration` at `9fedcce`, merged here). No toolchain file changed. Their suites `tests/web` (68) and `tests/graphql` (5) join the 3.9 job automatically, and `tests/infra/test_compose_hasura.py` joins the 3.13 job.
  - **`tests/web` fix.** Under the dev group, `test_timeout_clears_the_access_cookie_and_signs_the_user_out` failed because pytest-flask 1.3.0 pushes a request context around any test with an `app` fixture. On `mig/integration`'s own environment it passed. `-p no:flask` fixes it; no suite uses pytest-flask.
  - **Resolved.** After merging `68d55c7` (QA's re-recording), the local CI's 3.9 job gives 351 passed and 0 failed, with or without `CI=true`. `record.py --check` reports "85 cases, 0 fixture files would change", and the 3.13 job gives 108 passed. The history follows.
  - **Golden failure, not mine.** `tests/golden::test_druid_queries[policy_include_all_all_time]` fails on `mig/integration` itself, under its own WP-2a environment, and `record.py --check` here lists only that file ("85 cases, 1 fixture files would change"). This is the INV-2 change WP-0c causes, which WP-2a's file says to regenerate on a branch carrying WP-0c. Until QA regenerates it, the 3.9 job is red on every PR based on `mig/integration`. Request below.

### Requests to other roles

- [x] **qa (WP-2a follow-up), done in `eeb2db1`, merged here through `68d55c7`:** regenerate `tests/golden/cases/policy_include_all_all_time/druid_query.json` now that WP-0c is merged, following WP-2a's INV-2 note: `record.py --check` must list only that file, then a reviewer accepts the diff.

- [x] **lead:** `scripts/watch/watch_mypy.py` and `.vscode` now follow the pyproject mypy configuration and the ruff formatter (`17dcbce` on `mig/integration`, merged here).
- [x] **lead (done in `665401e`):** add `.hypothesis/` to `.gitignore`. The contract suite's property tests write a Hypothesis example database at the repo root (`tests/pipeline` turns it off).
- [ ] **lead:** delete the scripts nothing calls any more: `scripts/lint_python.sh`, `scripts/format_python.sh`, `scripts/format_python_files.sh`, `scripts/pylint/` and `scripts/mypy_parse.py`.
- [ ] **lead:** plan one repo-wide `ruff format` commit for a quiet point after phase 2, recorded in `.git-blame-ignore-revs`. ruff formats in black 24 style, so until then the first PR to touch a file gets a whole-file reformat. 283 files are affected (Decisions).
- [x] **data-platform:** (done by data-platform-1 on `mig/WP-2f-uv-ruff-mypy-ci-druid`) delete the dead code at `scripts/druid/druid_task_memory_stats.py:54-59`, which reads an undefined `raw_timestamp` (ruff F821), then delete its line in `[tool.ruff.lint.per-file-ignores]`.
- [x] **core** (done on `mig/WP-2f-uv-ruff-mypy-ci-core`, core-3): fix `util/unix.py:111`, where `subprocess` is undefined (ruff F821), then delete its line in `[tool.ruff.lint.per-file-ignores]`.
- [x] **Both side branches merged** (`ca8afea` druid, `d4ec15e` core). `[tool.ruff.lint.per-file-ignores]` now holds only the `tests/**` entry, and the tree-wide `ruff check --select E9,F63,F7,F82 .` passes with no exclusions.
  - Local CI: 3.9 job 352 passed (including `tests/core/test_unix.py`); 3.13 job 108 passed; mypy clean in both jobs.
  - Two new `noqa` lines in `util/unix.py` are for security's re-review. `S602` on the existing `Popen(..., shell=True)`: the reason is in the comment, since callers in `util/file/compression` pass a shell pipeline. `S110` on a deliberate `except Exception: pass` in the cleanup loop.
- [ ] **core, WP-3 follow-up (found while fixing the F821; not changed here).** In `util/unix.py`:
  - in `BackgroundProcess.wait()`, the `except CalledProcessError` can never run, because `Popen.wait` never raises it; and `wait()` never checks the exit code, so a failed child passes silently;
  - `finalize()` builds an error without raising it;
  - the errno 3 (`ESRCH`) handling re-raises in the case where the process was already killed, which is the case it should tolerate.
- [ ] **frontend-platform and qa:** no Jest or Playwright suite exists on `mig/integration`. Ask infra for a CI job when the first suite lands (Vitest in WP-6, Playwright smoke from QA).
- [ ] **qa (WP-2c), low:** no offline contract test pins the `date` format tag. Renaming it in `tests/contract/schema.py` left the suite green, while renaming `http-date` failed it (Unit 7 evidence). A `("2024-01-01", "date")` row in `test_string_format_tags` would close the gap.

## Log

- 2026-10-04 infra-2 unit 1: `pyproject.toml` (requirements.txt as `[project].dependencies`, groups `web`, `pipeline` and `dev`) and `uv.lock` for CPython 3.9. `tests/infra/conftest.py` keeps the 3.13 tool tests out of the 3.9 run. `tests/toolchain` import smoke test added, and `.venv` added to `.dockerignore`. Check: `uv lock --check` passes; `uv sync --locked` installs 231 packages (an earlier draft said 241, counting the first sync's pylint and black dependencies); `uv run pytest` 9 passed; WP-2a's `tests/golden` 226 passed under this environment.
- 2026-10-04 infra-2 unit 2: `docker/export_requirements.py` and `make requirements` generate `requirements*.txt` from `pyproject.toml`. The check test was written first and failed against the hand-written files. Check: tests/infra 84 passed; the line-by-line comparison under Evidence shows only the listed differences.
- 2026-10-04 infra-2 unit 3: ruff 0.16.10 replaces black and pylint (`ci/lint_python.sh`, `make lint-python` and `make format-python`); `.pylintrc` deleted. Check:
  - tree-wide `ruff check --select E9,F63,F7,F82` passes;
  - changed files pass `ruff check` and `ruff format --check`;
  - an added unused import and a misformatted line make the script exit 1;
  - shellcheck is clean.
- 2026-10-04 infra-2 unit 4: `mypy.ini` moved to `[tool.mypy]`. Check: the same 38 module overrides and the same files and plugin; `uv run mypy` reports "Success: no issues found in 523 source files", cold and warm cache, as `mypy --config-file mypy.ini` did before.
- 2026-10-04 infra-2 unit 5: `integration.yml` has jobs `python` (3.9: lock check, `uv sync --locked`, ruff, mypy, pytest) and `python-313` (standalone tools: strict mypy and `pytest tests/infra` from `ci/tools313/uv.lock`). `lint-js` lists changed files with `git diff` instead of `gh`, so no job has a token grant beyond `contents: read`. Also `make test`, and `-p no:selenium`. Check:
  - actionlint with shellcheck reports 0, and the WP-0f policy script passes;
  - every job command passes locally;
  - a deliberately broken golden case exits 1 and names the case.
- 2026-10-04 infra-2 unit 6: `.github/dependabot.yml` covers github-actions (weekly, grouped), `uv` at `/` (security updates only) and `uv` at `/ci/tools313` (weekly). Check: `check-jsonschema --builtin-schema vendor.dependabot` passes.
- 2026-10-04 infra-2: merged `mig/integration` (WP-0e). Every check above was re-run, all green.
- 2026-10-05 infra-2 unit 7 (review fixes and the WP-2c/2d suites):
  - **Build tools:** pinned with `[tool.uv] build-constraint-dependencies`; `uv.lock` records them.
  - **Merges:** `mig/integration` merged twice, first WP-2a, then the lead's fixes and `2086a21`.
  - **Dependencies:** `hypothesis==6.91.0` and `jsonschema==4.17.3` added to `dev`, and freezegun pinned at 1.5.5.
  - **3.9 job:** installs `lz4` and `pigz`.
  - **`ci/lint_python.sh`:**
    - diffs against the merge-base;
    - reads `git diff -z` with `core.quotePath=false` through a `read -d ''` loop instead of mapfile;
    - puts `--` before file lists (also for eslint and stylelint in the workflow);
    - in `--fix` mode, formats even when an error cannot be auto-fixed.
  - **Workflow:** setup-uv cache suffixes `app39` and `tools313`, plus a concurrency group.
  - **Exporter:** normalises names, rejects unused sources and non-SHA revs, and its test requires new lines to be `==`-pinned.
  - **Dependabot:** 7-day cooldown.
  - **ruff:** `S` rules on changed files.

  Check (details under Evidence):
  - fresh-cache `uv sync --locked -v` installs only the pinned build tools;
  - all five suites pass: 756 passed and 166 skipped in the 3.9 job with 2c and 2d overlaid, and 91 passed in the 3.13 job;
  - golden, pipeline and contract breaks each exit 1 and name the case;
  - actionlint 0, zizmor 0 findings, and the WP-0f policy passes;
  - `git ls-files .playwright-mcp` is empty.
- 2026-10-05 data-platform-1 (request, branch `mig/WP-2f-uv-ruff-mypy-ci-druid`): in `scripts/druid/druid_task_memory_stats.py`, deleted the unreachable second `return` in `build_timestamp`. It read the undefined `raw_timestamp`, and the function returns on its first line. Nothing else in the file reads `raw_timestamp`. Removed the file's F821 entry from `[tool.ruff.lint.per-file-ignores]`. Touching the file subjects it to the full changed-file rules, which flagged S101 on `assert False` in `_convert_to_mb`. It now raises `ValueError` for an unknown unit; before, it raised `AssertionError`, or under `-O` returned `'ERR'`. Check: the old file gives 6 errors under `ruff check --select E9,F63,F7,F82` without the ignore; `ci/lint_python.sh mig/WP-2f-uv-ruff-mypy-ci` exits 0 (tree-wide check passes, changed file lint-clean and formatted); the script on a sample filtered GC log writes `2026-10-04 16:14:20	30.5	1024.0	9.5	1000.0`.
- 2026-10-04 core-3: `util/unix.py` `BackgroundProcess.wait` catches the already-imported `CalledProcessError` instead of the undefined `subprocess.CalledProcessError`, so an error from `Popen.wait()` (e.g. Ctrl-C) now propagates as itself instead of becoming a `NameError`; its `F821` per-file ignore is gone. That was the module's only undefined name. Touching the file brought it under the full rule set: `# noqa: S602` on the `shell=True` `Popen` (its callers in `util/file/compression` pass shell pipelines, for security to review), `# noqa: S110` on the deliberate swallow in `finalize`, and one blank line from `ruff format`. Check: `tests/core/test_unix.py` failed with `NameError` before and passes after; `ci/lint_python.sh mig/WP-2f-uv-ruff-mypy-ci` exit 0; a gzip round trip through `CommandLineCompressor`/`CommandLineDecompressor` returns the input.

## Decisions

- **Two Python lanes until WP-3b.**
  - The app's suites run on CPython 3.9 from `uv.lock`.
  - Standalone 3.13 tools (`prod/browser_share`, `docker/export_requirements.py`) and their tests in `tests/infra` run from `ci/tools313/uv.lock`.
  - `tests/infra/conftest.py` stops the 3.9 run collecting them.

  Moving to 3.13 means two things. First, change `requires-python = "==3.9.*"` to `"==3.13.*"` in `pyproject.toml` and run `uv lock`; the pins that cannot install on 3.13 (numpy 1.21.0, pandas < 2 and others) are WP-3a's job. Second, delete `ci/tools313` and the conftest guard. Every new suite under `tests/` runs in the 3.9 job with no workflow change.
- **The requirements files are generated verbatim, not exported from the lock.**
  - The web image is CPython 3.8 (`docker/web/Dockerfile_web-server`), and the pipeline image installs the same files into a PyPy venv. A 3.9 CPython lock does not describe either. Copying the requirement strings keeps the images' pip input as it was.
  - Exact line differences: two redundant lines dropped from `requirements.txt`, `wheel>=0.26.0` (subsumed by `wheel==0.43.0`) and the second `attrs==21.4.0`; in `requirements-dev.txt`, `freezegun>=1.5` added for the golden suite, and black and pylint replaced by `ruff==0.16.10`.
  - Comments moved into `pyproject.toml`.
  - WP-3b moves the images to `uv sync --locked` and deletes the script and the files.
- **The lock covers CPython only** (`environments`). It overrides `psycopg2-binary` to 2.8.6, because 2.8.5 has no cp39 wheel and fails to build without libpq headers; WP-2a made the same choice. `requirements.txt` keeps 2.8.5 for the images.
- **Ruff scope.**
  - The tree is neither lint-clean (336 findings under E4, E7, E9 and F, 298 of them F401) nor formatted, and most of it is owned by other roles. So the whole tree gets only what ruff can prove is broken: E9, F63, F7 and F82. Two existing F821 bugs are listed in per-file ignores and in Requests.
  - The full set (E4, E7, E9, F and S) and `ruff format --check` apply to the Python files a PR changes, measured from the merge-base with the base branch.
  - **This is a ratchet.** pylint failed CI only on `type == error`, so unused imports (F401) and other warnings used to pass. Now any F401 in a changed file fails, as does any unformatted changed file. In-flight branches are told under Merge-order items.
  - **S (bandit) rules, at security's request.** S101 (assert) and S311 (`random`) are ignored under `tests/**`. S603 and S607 are ignored everywhere: they flag every `subprocess` call, including fixed argument lists with no shell, and fired on every subprocess call in `scripts/agents`. The shell rules S602, S604 and S605 stay on.
  - ruff ignores `# pylint: disable` comments (412 in the tree). Touching such a file means turning, for example, `# pylint:disable=W0611` into `# noqa: F401`.
  - ruff's formatter follows black 24, not black 22.6. Of the 655 files under `web/server`, `data`, `models` and `db` that black 22.6 accepts, ruff would reformat 239. Repo-wide, 283 files would change, mostly blank lines after docstrings and parenthesised right-hand sides. Hence the lead request for one format commit.
- **Changed files come from `git diff HEAD^1 HEAD`** on the PR merge commit (`fetch-depth: 2`), not `gh pr view`. Every job now needs only `contents: read`, and no step holds `GITHUB_TOKEN` except inside `setup-uv`, which uses it for its downloads.
- **`pytest-selenium` is disabled** (`addopts = "-p no:selenium"`). The `dev` group pins 4.0.1, and on pytest 8.4.2 it raises an INTERNALERROR whenever a test fails. The run still exits 3, but the failing test is hidden. No suite uses it.
- **Build tools are locked too.** `uv sync` builds 29 packages from source: 3 git dependencies and 26 sdists, gevent among them. `[tool.uv] build-constraint-dependencies` pins every build requirement a fresh-cache sync installs:
  - `setuptools==82.0.1`;
  - `cython==3.3.0`;
  - `cffi==2.0.0`;
  - `greenlet==3.2.5`;
  - `pycparser==2.23`;
  - `pytest-runner==6.0.1`.

  These are the versions those builds resolved before the pin, so nothing they produce changes. uv 0.12.5 writes them to `[manifest] build-constraints` in `uv.lock`, and `--locked` refuses a sync when `pyproject.toml` and the lock disagree. The constraints pin versions but carry no hashes; the runtime packages in the lock are hashed. A new source-built package with a new build requirement shows up in the fresh-cache check under Evidence; Dependabot does not cover this.
- **Pins outside the lock.** setup-uv v10.2.0 is pinned by SHA, and the uv binary at `0.12.5`, which setup-uv checks against its checksum manifest. The 3.13 lane's pytest 9.1.1 and mypy 2.4.0 are locked with hashes in `ci/tools313/uv.lock`.
- **Dependabot for the root `uv` project is security-only** (`open-pull-requests-limit: 0`), because the app's pins are deliberate until WP-3a and WP-3b. Its PRs must also run `make requirements`, which the export test enforces.

## Evidence

The commands in this first part ran after merging `mig/integration` at `e0c8228`. Unit 7 evidence follows.

- **Python job, local** (`/tmp/wp2f/ci_local.sh <worktree> mig/integration`). Every step exits 0:
  - `uv lock --check`, for both projects;
  - `uv sync --locked`;
  - `ci/lint_python.sh mig/integration`, where the tree-wide check reports "All checks passed!" and the 4 changed Python files pass lint and format;
  - `uv run --locked mypy`: "Success: no issues found in 523 source files";
  - `uv run --locked pytest -m 'not stack'`: 9 passed;
  - 3.13 lane mypy `--strict`: "Success: no issues found in 2 source files";
  - 3.13 lane `pytest tests/infra`: 84 passed.
- **actionlint 1.7.12 with shellcheck 0.11.0:** 0 findings. The WP-0f policy script (`/tmp/wp0f-sim/policy.py`) reports `policy OK`: top-level `permissions: {}`, per-job `contents: read` only, `ubuntu-24.04`, 40-hex SHA pins, no `${{` inside `run:`, no `GH_TOKEN`. `check-jsonschema --builtin-schema vendor.dependabot .github/dependabot.yml`: ok.
- **Deliberately broken case, the phase 2 exit check.**
  1. With WP-2a's `tests/golden` overlaid (`git archive mig/WP-2a-golden-query-suite tests/golden`, not committed), `uv run --locked pytest -m 'not stack'` gave 235 passed.
  2. Changing `366.84` to `366.85` in `tests/golden/cases/table_no_groups/expected_response.json` made it exit 1 with `FAILED tests/golden/test_golden_queries.py::test_response[table_no_groups]` and the diff `- es": 366.85`.
  3. Restored, 235 passed.
  4. Before `-p no:selenium`, the same break gave exit 3 with an INTERNALERROR from `pytest_selenium.py:280`, which hid the failing case.

  Also, `ci/lint_python.sh` exits 1 on an added unused import plus a misformatted line, and 0 once they are reverted.
- **Requirements equivalence** (`/tmp/wp2f/compare_requirements.py` against copies of the hand-written files):
  - `requirements-web.txt`: 16 lines, the same parsed requirements in the same order (the comparison ignores comments and blank lines, so the files are not byte-identical);
  - `requirements-pipeline.txt`: 23 lines, the same parsed requirements in the same order;
  - `requirements.txt`: 50 lines before, 48 after; the only lines gone are `wheel>=0.26.0` and the duplicate `attrs==21.4.0`;
  - `requirements-dev.txt`: `freezegun>=1.5` added, and after unit 3 black and pylint swapped for ruff.
- **mypy configuration parity:** the 38 `[mypy-*]` sections of `mypy.ini` and the modules in `[[tool.mypy.overrides]]` compare equal (`LC_ALL=C sort | diff`). One warm-cache run right after the switch reported an error inside `pkg_resources`, from a `.mypy_cache` built under `mypy.ini`. Cold (`--cache-dir` fresh) and warm runs since then are clean.
### Unit 7 evidence

These ran after merging `mig/integration` at `2988d85`. `git ls-files .playwright-mcp` is empty.

- **Build constraints.**
  - Before the pin, a fresh-cache `UV_CACHE_DIR=<new> UV_PROJECT_ENVIRONMENT=<new> uv sync --locked -v` built 29 packages, with build requirements resolved at sync time: `setuptools==82.0.1` ×31, `pycparser==2.23` ×3, `greenlet==3.2.5` ×3, `cffi==2.0.0` ×3, `pytest-runner==6.0.1` ×2 and `cython==3.3.0` ×1. None of these was in `uv.lock`.
  - After the pin, the same fresh-cache command exits 0, builds the same 29 packages, installs exactly those build requirements, and installs 232 packages. `uv.lock` holds them under `[manifest] build-constraints`.
  - **Enforcement, in a scratch project** with `stringcase==1.2.0` (sdist) and the build constraint `setuptools==75.8.0`:
    - a fresh-cache `uv sync --locked -v` logs `Installing build requirement: setuptools==75.8.0`, not the newest release;
    - changing the constraint in `pyproject.toml` without re-locking makes `uv sync --locked` refuse ("To update the lockfile, run `uv lock`").
- **All suites, with WP-2c and WP-2d overlaid** (`git archive` of `tests/contract` and `tests/pipeline`, not committed), run with `CI=true` as on the runner:
  - collection in the 3.9 job: `tests/contract` 540, `tests/golden` 269, `tests/pipeline` 104, `tests/toolchain` 9;
  - `uv run --locked pytest -m 'not stack'`: 756 passed and 166 skipped. The skips are the contract replay cases, through the `CONTRACT_BASE_URL` fixture;
  - 3.13 job `pytest tests/infra`: 91 passed (79 browser share, 12 exporter);
  - `tests/pipeline` used the local `lz4` and `lz4cat`, and fell back to `gzip` because this machine has no `pigz`. CI installs `pigz`.
- **Deliberately broken cases, repeated** (`/tmp/wp2f/broken_cases.sh`; each file is restored after its run):

  | Suite | Break | Exit | Named |
  |---|---|---|---|
  | golden | `366.84` → `366.85` in `table_no_groups/expected_response.json` | 1 | `test_response[table_no_groups]` |
  | pipeline | first `"yellow_fever_cases": 1,` → `2,` in `demo__yellow_fever_end_to_end/canonical/processed_data.base_rows.jsonl` | 1 | `test_outputs_match_golden[demo__yellow_fever_end_to_end-canonical]` |
  | contract (offline) | format tag `http-date` → `http-day` in `tests/contract/schema.py` | 1 | `test_string_format_tags[...-http-date]`, `test_diff_explains_serialisation_and_key_drift` |
  | restored | none | 0 | 756 passed, 166 skipped |

  A first contract attempt (renaming the `date` tag) stayed green: no offline test pins that tag. I record it as a gap for QA, not a CI fault.
- **Lint script.**
  - Against `mig/WP-0b-ports-secrets-pins`, the old two-dot diff listed 10 Python files, including `config/settings.py` and `web/server/app.py`, which only the base changed. `--merge-base` lists only 4.
  - In `--fix` mode, an added unused import was removed and a misformatted line reformatted, while the unfixable F821 on the same line was still reported, exit 1. Clean, it exits 0.
  - shellcheck is clean.
  - eslint 7.32 and stylelint 13.13 both lint a file named `-bad name.js` / `-x.scss` passed after `--`.
- **Exporter.** The new tests failed first:
  - names are normalised (`flask_potion` matches source `Flask-Potion`);
  - an unused source exits 2;
  - revs `main`, `v1.0`, a 12-character SHA and an uppercase SHA each exit 2;
  - every line is `==`-pinned unless it is on the adoption allowlist. Reverting freezegun to `>=1.5` fails with `['freezegun>=1.5']`.

  `mypy --strict` on the exporter is clean.
- **Workflows.**
  - actionlint 1.7.12 with shellcheck 0.11.0: 0 findings;
  - WP-0f policy script: `policy OK`;
  - zizmor 1.30.1 `--offline`: "No findings to report". Its 12 suppressed items are pedantic-persona notes: 6 anonymous definitions, 4 undocumented permissions, and 2 concurrency-limit notes on the push-only image workflows (`web.yml`, `pipeline.yml`);
  - `check-jsonschema --builtin-schema vendor.dependabot`: ok.
- **Not verified.** No GitHub run yet: the lead asked not to push before the gates pass. The first PR run will show:
  - how long `uv sync` takes cold on the runner (about 4.5 minutes locally, most of it building sdists);
  - that `setup-uv` restores the cache;
  - the timing of the python-313 job.

  Dependabot only runs after merge to the default branch.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 qa-2f at 7b2f9b6: lock, cold uv sync (231 pkgs), CI run blocks replayed on a simulated PR merge commit, mypy parity with mypy.ini, requirements drift test, broken-case exit codes, actionlint 0 and WP-0f policy, new SHAs match tags. Follow-ups: hypothesis (and 2c/2d deps) in the dev group; make format-python stops on unfixable errors; druid_task_memory_stats dead code (delete); .vscode points at black (lead). |
| reviewer | changes-requested | 2026-10-04 rev-2f at 7b2f9b6: design and parity sound. Fix: answer WP-2c/2d requests (hypothesis in dev; who runs stack suites; correct the 'turns PRs red' and 'run elsewhere' claims); lint script must diff against the merge-base; separate setup-uv cache keys per job; exporter must normalise names and fail on unused uv sources; mypy.ini deletion breaks watch_mypy.py and .vscode (lead fix must land in the same stack); describe the F401 ratchet and warn in-flight branches (list WP-0b in the porting request); mapfile needs bash 4; add a concurrency group. |
| security | changes-requested | 2026-10-05 sec-2f at 7b2f9b6: workflow privileges and pins sound; lock fully hashed. Medium: uv sync builds 29 packages from source with build tools resolved unlocked at CI time (setuptools 82, cython, cffi, greenlet, pycparser, pytest-runner): add build-constraint-dependencies and re-lock. Low: Dependabot cooldown; exporter does not enforce pins (name normalisation, rev SHA, freezegun>=1.5 copied unpinned);  before file lists and quotePath; add ruff S rules (S101 ignored under tests). |
