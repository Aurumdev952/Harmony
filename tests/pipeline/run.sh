#!/usr/bin/env bash
# Run the pipeline fixture suite, or regenerate its goldens.
#   tests/pipeline/run.sh [pytest args]
#   tests/pipeline/run.sh regenerate [CASE ...] [--print]
# By default the suite runs on the root uv.lock environment (CPython 3.13, as the
# pipeline image). PIPELINE_FIXTURE_PYTHON picks another interpreter instead (for
# example 3.9 or pypy3.9, what the pipeline ran before WP-3b), with requirements.txt.
set -euo pipefail

suite_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${suite_dir}/../.." && pwd)"
export ZEN_ENV=harmony_demo
export HYPOTHESIS_STORAGE_DIRECTORY="${HYPOTHESIS_STORAGE_DIRECTORY:-${TMPDIR:-/tmp}/harmony-pipeline-fixtures-hypothesis}"

if [[ -n "${PIPELINE_FIXTURE_PYTHON:-}" ]]; then
  uv_run=(uv run --no-project --python "${PIPELINE_FIXTURE_PYTHON}" --with-requirements "${suite_dir}/requirements.txt")
else
  uv_run=(uv run --locked --project "${repo_root}")
fi

if [[ "${1:-}" == "regenerate" ]]; then
  shift
  exec "${uv_run[@]}" python "${suite_dir}/regenerate.py" "$@"
fi
exec "${uv_run[@]}" python -m pytest --rootdir "${repo_root}" -p no:cacheprovider "${suite_dir}" "$@"
