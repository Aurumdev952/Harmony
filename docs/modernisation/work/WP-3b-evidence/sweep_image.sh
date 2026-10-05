#!/usr/bin/env bash
# sweep_image.sh <image> <out.tsv> [user]: import every first-party module the web
# image carries (config data db log models graphql util web), in one process, as
# <user> (default 1000), with dummy settings.
set -uo pipefail
IMG="$1"
OUT="$2"
RUN_USER="${3:-1000}"
SWEEP=$(cd "$(dirname "$0")/../WP-0d-evidence" && pwd -P)/import_sweep.py
docker run --rm --user "$RUN_USER" --network none --entrypoint python \
  -v "$SWEEP":/sweep.py:ro -w /zenysis \
  -e ZEN_ENV=harmony_demo -e DRUID_HOST=http://127.0.0.1 \
  -e POSTGRES_HOST=127.0.0.1 -e POSTGRES_USER=u -e POSTGRES_PASSWORD=p \
  -e DATABASE_URL=postgresql://u:p@127.0.0.1:1/x -e SQLALCHEMY_DATABASE_URI=postgresql://u:p@127.0.0.1:1/x \
  -e DEFAULT_SECRET_KEY=sweep-default-key-0123456789abcdef -e JWT_SECRET_KEY=sweep-jwt-key-fedcba9876543210 \
  -e PYTHONPATH=/zenysis -e ZEN_HOME=/zenysis -e R77_SRC_ROOT=/zenysis -e ZEN_OFFLINE=1 \
  "$IMG" /sweep.py config data db log models graphql util web 2>/dev/null </dev/null \
  | grep -P '\t' | sort > "$OUT"
cut -f2 "$OUT" | cut -c1-3 | sort | uniq -c
