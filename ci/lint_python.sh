#!/usr/bin/env bash
# Lint the whole tree for what ruff can prove is broken (syntax errors, undefined
# names), then lint and format-check the Python files this branch changed since
# its merge-base with <base>. The tree is not yet formatted or lint-clean, so the
# full rule set applies only to the files a change touches. With --fix, fix and
# format those files instead.
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

# Resolved before anything else, so set -e stops on a bad ref or a shallow clone
# instead of reporting "no Python files changed".
merge_base=$(git merge-base HEAD "$base")
changed_list=$(mktemp)
trap 'rm -f "$changed_list"' EXIT
git -c core.quotePath=false diff -z --name-only --diff-filter=d "$merge_base" -- '*.py' >"$changed_list"

status=0
uv run --locked ruff check --select E9,F63,F7,F82 . || status=1

# NUL-separated and unquoted, so any file name survives; no mapfile (bash 3.2).
changed=()
while IFS= read -r -d '' file; do
  changed+=("$file")
done <"$changed_list"

if ((${#changed[@]} == 0)); then
  echo "no Python files changed since the merge-base with $base"
  exit "$status"
fi
echo "changed since the merge-base with $base: ${changed[*]}"

if $fix; then
  # Format even when some lint errors are not auto-fixable; report them after.
  uv run --locked ruff check --force-exclude --fix -- "${changed[@]}" || status=1
  uv run --locked ruff format --force-exclude -- "${changed[@]}"
  exit "$status"
fi

uv run --locked ruff check --force-exclude -- "${changed[@]}" || status=1
uv run --locked ruff format --force-exclude --check -- "${changed[@]}" || status=1
exit "$status"
