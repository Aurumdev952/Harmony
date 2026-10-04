#!/bin/bash
# Runs the authorisation suite on the root uv project (the pinned legacy web
# stack: Flask 1.0.1, the Flask-Potion fork). PyYAML and Hypothesis are added
# for the run until WP-2f folds the suites' needs into the dev group.
#
#   tests/authz/run.sh                 # no-server layer (select with -k, not paths)
#   tests/authz/run.sh -m authz_http   # live-stack layer; eval "$(tests/authz/stack.sh env)" first
set -euo pipefail

cd "$(dirname "$0")/../.."
uv run --with pyyaml --with hypothesis \
  pytest tests/authz -q -p no:cacheprovider -W ignore "$@"
