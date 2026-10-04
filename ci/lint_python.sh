#!/usr/bin/env bash
# Lint the whole tree for what ruff can prove is broken (syntax errors, undefined
# names), then lint and format-check the Python files changed since <base>. The
# tree is not yet formatted or lint-clean, so the full rule set applies to the
# files a change touches. With --fix, fix and format those files instead.
#
#   ci/lint_python.sh main          # CI passes HEAD^1, the PR's base
#   ci/lint_python.sh --fix main
set -euo pipefail

fix=false
if [[ ${1:-} == --fix ]]; then
  fix=true
  shift
fi
base=${1:?usage: ci/lint_python.sh [--fix] <base-ref>}
cd "$(git rev-parse --show-toplevel)"

uv run --locked ruff check --select E9,F63,F7,F82 .

mapfile -t changed < <(git diff --name-only --diff-filter=d "$base" -- '*.py')
if ((${#changed[@]} == 0)); then
  echo "no Python files changed since $base"
  exit 0
fi
echo "changed since $base: ${changed[*]}"

if $fix; then
  uv run --locked ruff check --force-exclude --fix "${changed[@]}"
  uv run --locked ruff format --force-exclude "${changed[@]}"
  exit 0
fi

status=0
uv run --locked ruff check --force-exclude "${changed[@]}" || status=1
uv run --locked ruff format --force-exclude --check "${changed[@]}" || status=1
exit "$status"
