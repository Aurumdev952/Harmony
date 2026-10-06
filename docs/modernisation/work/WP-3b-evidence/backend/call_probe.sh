#!/usr/bin/env bash
# call_probe.sh <image>: call the helpers that used the removed `collections` ABC
# aliases inside a web image, as uid 1000, with dummy settings and no network.
set -uo pipefail
IMG="$1"
PROBE=$(cd "$(dirname "$0")" && pwd -P)/call_probe.py
docker run --rm --user 1000 --network none --entrypoint python \
  -v "$PROBE":/probe.py:ro -w /zenysis \
  -e ZEN_ENV=harmony_demo -e DRUID_HOST=http://127.0.0.1 \
  -e DATABASE_URL=postgresql://u:p@127.0.0.1:1/x -e SQLALCHEMY_DATABASE_URI=postgresql://u:p@127.0.0.1:1/x \
  -e DEFAULT_SECRET_KEY=sweep-default-key-0123456789abcdef -e JWT_SECRET_KEY=sweep-jwt-key-fedcba9876543210 \
  -e PYTHONPATH=/zenysis -e ZEN_HOME=/zenysis -e R77_SRC_ROOT=/zenysis -e ZEN_OFFLINE=1 \
  "$IMG" /probe.py 2>/dev/null </dev/null
