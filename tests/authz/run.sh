#!/bin/bash
# Runs the authorisation suite on the web server's pinned stack (Python 3.8,
# Flask 1.0.1, Flask-Potion fork). There is no pyproject.toml yet, and uv rejects
# `-e git+...` requirement lines, so they are rewritten into direct references.
#
#   tests/authz/run.sh                 # pure layer (select with -k, not paths)
#   tests/authz/run.sh -m authz_http   # live-stack layer; eval "$(tests/authz/stack.sh env)" first
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
REQS="$(mktemp)"
trap 'rm -f "${REQS}"' EXIT

sed -E 's/^-e (git\+.*#egg=(.*))$/\2 @ \1/; s/#egg=.*$//' \
  "${ROOT}/requirements.txt" "${ROOT}/requirements-web.txt" \
  | grep -v 'segment-analytics\|google-cloud-logging\|Flask-Admin\|graphene\|Flask-GraphQL' \
  > "${REQS}"

cd "${ROOT}"
PYTHONPATH="${ROOT}" exec uv run --no-project -p 3.8 \
  --with-requirements "${REQS}" --with 'pytest<8' --with pyyaml --with requests \
  python -m pytest tests/authz -q -p no:cacheprovider -W ignore "$@"
