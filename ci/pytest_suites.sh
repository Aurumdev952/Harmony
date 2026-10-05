#!/usr/bin/env bash
# Run every suite under tests/ (one directory each) in its own pytest process on
# the uv.lock environment. Suites from different WPs build Flask apps and register
# Flask-Potion resources at module level, so sharing one process makes them fail
# by order. A new directory under tests/ runs with no change here. Extra arguments
# go to pytest.
#
#   ci/pytest_suites.sh
#   ci/pytest_suites.sh -x -q
set -euo pipefail
shopt -s nullglob
cd "$(git rev-parse --show-toplevel)"

targets=()
for suite in tests/*/; do
  suite=${suite%/}
  [[ $suite == */__pycache__ ]] && continue
  targets+=("$suite")
done
loose=(tests/test_*.py)
if ((${#loose[@]})); then
  targets+=("${loose[@]}")
fi

failed=()
for target in "${targets[@]}"; do
  echo "== pytest $target"
  code=0
  uv run --locked pytest -m 'not stack' "$@" -- "$target" || code=$?
  # 5: every test in the suite was deselected (all `stack`), which is not a failure.
  if ((code == 5)); then
    echo "$target: no tests selected"
  elif ((code != 0)); then
    failed+=("$target")
  fi
done

if ((${#failed[@]})); then
  echo "failed suites: ${failed[*]}" >&2
  exit 1
fi
echo "all ${#targets[@]} suites passed"
