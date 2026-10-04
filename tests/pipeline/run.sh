#!/usr/bin/env bash
# Run the pipeline fixture suite, or regenerate its goldens.
#   tests/pipeline/run.sh [pytest args]
#   tests/pipeline/run.sh regenerate [CASE ...] [--print]
# PIPELINE_FIXTURE_PYTHON picks the interpreter: 3.9 (default, the pipeline image's
# CPython) or pypy3.9 (what the Zeus steps run today). 3.12+ cannot import config/ yet.
set -euo pipefail

suite_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${suite_dir}/../.." && pwd)"
python="${PIPELINE_FIXTURE_PYTHON:-3.9}"
export ZEN_ENV=harmony_demo
export HYPOTHESIS_STORAGE_DIRECTORY="${HYPOTHESIS_STORAGE_DIRECTORY:-${TMPDIR:-/tmp}/harmony-pipeline-fixtures-hypothesis}"

uv_run=(uv run --no-project --python "${python}" --with-requirements "${suite_dir}/requirements.txt")

if [[ "${1:-}" == "regenerate" ]]; then
  shift
  exec "${uv_run[@]}" python "${suite_dir}/regenerate.py" "$@"
fi
exec "${uv_run[@]}" python -m pytest --rootdir "${repo_root}" -p no:cacheprovider "${suite_dir}" "$@"
