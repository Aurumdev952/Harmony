#!/usr/bin/env bash
# Run the pipeline fixture suite, or regenerate its goldens.
#   tests/pipeline/run.sh [pytest args]
#   tests/pipeline/run.sh regenerate [CASE ...] [--print]
# The suite runs on the root uv.lock environment (CPython 3.13), as the pipeline
# image does.
set -euo pipefail

suite_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${suite_dir}/../.." && pwd)"
export ZEN_ENV=harmony_demo
export HYPOTHESIS_STORAGE_DIRECTORY="${HYPOTHESIS_STORAGE_DIRECTORY:-${TMPDIR:-/tmp}/harmony-pipeline-fixtures-hypothesis}"

uv_run=(uv run --locked --project "${repo_root}")

if [[ "${1:-}" == "regenerate" ]]; then
  shift
  exec "${uv_run[@]}" python "${suite_dir}/regenerate.py" "$@"
fi
exec "${uv_run[@]}" python -m pytest --rootdir "${repo_root}" -p no:cacheprovider "${suite_dir}" "$@"
