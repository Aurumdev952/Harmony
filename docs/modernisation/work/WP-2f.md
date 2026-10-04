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

## Contract changes

None.

## Requests

None of these blocks this WP.

- [ ] **qa (WP-2c):** mark the tests that need the compose stack (`tests/contract/test_replay.py`) with `@pytest.mark.stack`. CI's pytest step runs `-m 'not stack'`, so unmarked stack tests turn every PR red. Also keep `tests/conftest.py` free of module-level imports of 3.9-only app code: the 3.13 job runs `pytest tests/infra` and loads it.
- [ ] **qa / lead (WP-2a merge):** WP-2a's `pyproject.toml` and `uv.lock` conflict with this WP's. Take WP-2f's versions and drop the `golden` group. They are a superset: WP-2a's `tests/golden` passes under this environment, 226 cases (Evidence).
- [ ] **core and infra (WP-0d side branches):** `mig/WP-0d-dead-backend-code-infra` edits `requirements*.txt` and `mypy.ini`. Whichever WP merges second ports the change:
  - removed packages go out of `pyproject.toml` (`[project].dependencies` or the matching group), followed by `uv lock` and `make requirements`;
  - removed mypy overrides go out of `[[tool.mypy.overrides]]`.
- [ ] **merge order, WP-0b (bcrypt):** WP-0b pins `bcrypt==4.0.1` in `requirements.txt`, next to flask-user. `requirements.txt` is generated after this WP, so when WP-0b lands on `mig/integration`, the pin moves into `[project].dependencies` in `pyproject.toml`. After that, `uv lock` (today's lock resolves bcrypt 5.0.0) and `make requirements`. Until then the lock stays as it is. `tests/infra/test_requirements.py` from WP-0b reads `requirements.txt` and runs in the 3.13 lane, which reads the generated file, so it keeps working. WP-0b's suites `tests/core`, `tests/web` and `tests/druid_setup` join the 3.9 job automatically. Re-run the full local CI on that merge to confirm none of them needs the stack (they would then need the `stack` marker).
- [ ] **lead:** delete the scripts nothing calls any more: `scripts/lint_python.sh`, `scripts/format_python.sh`, `scripts/format_python_files.sh`, `scripts/pylint/` and `scripts/mypy_parse.py`. Change `scripts/watch/watch_mypy.py:36`, which passes `--config-file mypy.ini`; that file no longer exists, so `yarn mypy` and `yarn develop` fail until the flag goes (dmypy reads `[tool.mypy]` from `pyproject.toml`).
- [ ] **lead:** plan one repo-wide `ruff format` commit for a quiet point after phase 2, recorded in `.git-blame-ignore-revs`. Until then, CI format-checks only the files a PR touches. ruff formats in black 24 style, so the first PR to touch a file gets a whole-file reformat. 283 files are affected (Decisions).
- [ ] **core:** fix `util/unix.py:111`, where `subprocess` is undefined (ruff F821). This is a real bug. Then delete its line in `[tool.ruff.lint.per-file-ignores]`.
- [ ] **data-platform:** fix `scripts/druid/druid_task_memory_stats.py:54-59`, where `raw_timestamp` is undefined (ruff F821). This is a real bug. Then delete its line in `[tool.ruff.lint.per-file-ignores]`.
- [ ] **frontend-platform and qa:** no Jest or Playwright suite exists on `mig/integration` (Jest is in `package.json`, but there are no test files and no `e2e/`). Ask infra for a CI job when the first suite lands (Vitest in WP-6, Playwright smoke from QA).

## Log

- 2026-10-04 infra-2 unit 1: `pyproject.toml` (requirements.txt as `[project].dependencies`, groups `web`, `pipeline` and `dev`) and `uv.lock` for CPython 3.9. `tests/infra/conftest.py` keeps the 3.13 tool tests out of the 3.9 run. `tests/toolchain` import smoke test added, and `.venv` added to `.dockerignore`. Check: `uv lock --check` passes; `uv sync --locked` installs 241 packages; `uv run pytest` 9 passed; WP-2a's `tests/golden` 226 passed under this environment.
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
  - The full set (E4, E7, E9, F) and `ruff format --check` apply to the Python files a PR changes, as black and pylint did.
  - ruff ignores `# pylint: disable` comments (412 in the tree). Touching such a file means turning, for example, `# pylint:disable=W0611` into `# noqa: F401`.
  - ruff's formatter follows black 24, not black 22.6. Of the 655 files under `web/server`, `data`, `models` and `db` that black 22.6 accepts, ruff would reformat 239. Repo-wide, 283 files would change, mostly blank lines after docstrings and parenthesised right-hand sides. Hence the lead request for one format commit.
- **Changed files come from `git diff HEAD^1 HEAD`** on the PR merge commit (`fetch-depth: 2`), not `gh pr view`. Every job now needs only `contents: read`, and no step holds `GITHUB_TOKEN` except inside `setup-uv`, which uses it for its downloads.
- **`pytest-selenium` is disabled** (`addopts = "-p no:selenium"`). The `dev` group pins 4.0.1, and on pytest 8.4.2 it raises an INTERNALERROR whenever a test fails. The run still exits 3, but the failing test is hidden. No suite uses it.
- **Pins outside the lock.** setup-uv v10.2.0 is pinned by SHA, and the uv binary at `0.12.5`, which setup-uv checks against its checksum manifest. The 3.13 lane's pytest 9.1.1 and mypy 2.4.0 are locked with hashes in `ci/tools313/uv.lock`.
- **Dependabot for the root `uv` project is security-only** (`open-pull-requests-limit: 0`), because the app's pins are deliberate until WP-3a and WP-3b. Its PRs must also run `make requirements`, which the export test enforces.

## Evidence

All commands below ran on the branch after merging `mig/integration` at `e0c8228`.

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
  - `requirements-web.txt`: 16 lines, identical and in the same order;
  - `requirements-pipeline.txt`: 23 lines, identical and in the same order;
  - `requirements.txt`: 50 lines before, 48 after; the only lines gone are `wheel>=0.26.0` and the duplicate `attrs==21.4.0`;
  - `requirements-dev.txt`: `freezegun>=1.5` added, and after unit 3 black and pylint swapped for ruff.
- **mypy configuration parity:** the 38 `[mypy-*]` sections of `mypy.ini` and the modules in `[[tool.mypy.overrides]]` compare equal (`LC_ALL=C sort | diff`). One warm-cache run right after the switch reported an error inside `pkg_resources`, from a `.mypy_cache` built under `mypy.ini`. Cold (`--cache-dir` fresh) and warm runs since then are clean.
- **Not verified.** No GitHub run yet: the lead asked not to push before the gates pass. The first PR run will show:
  - how long `uv sync` takes cold on the runner (about 4.5 minutes locally, most of it building sdists);
  - that `setup-uv` restores the cache;
  - the timing of the python-313 job.

  Dependabot only runs after merge to the default branch.

## Verdicts

| Role | Verdict | Notes |
|---|---|---|
| qa | approved | 2026-10-04 qa-2f at 7b2f9b6: lock, cold uv sync (231 pkgs), CI run blocks replayed on a simulated PR merge commit, mypy parity with mypy.ini, requirements drift test, broken-case exit codes, actionlint 0 and WP-0f policy, new SHAs match tags. Follow-ups: hypothesis (and 2c/2d deps) in the dev group; make format-python stops on unfixable errors; druid_task_memory_stats dead code (delete); .vscode points at black (lead). |
| reviewer | pending | |
| security | pending | |
