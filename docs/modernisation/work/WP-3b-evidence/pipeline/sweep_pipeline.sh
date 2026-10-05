#!/usr/bin/env bash
# sweep_pipeline.sh <image> <out.tsv> <python>: import every first-party module the
# pipeline image carries, in one process, as uid 1000, with dummy settings.
IMG="$1"; OUT="$2"; PY="$3"
SWEEP=$(cd "$(dirname "$0")/../../WP-0d-evidence" && pwd -P)/import_sweep.py
docker run --rm --user 1000:1000 --network none --entrypoint "$PY" \
  -v "$SWEEP":/sweep.py:ro -w /zenysis \
  -e ZEN_ENV=harmony_demo -e DRUID_HOST=http://127.0.0.1 \
  -e POSTGRES_HOST=127.0.0.1 -e POSTGRES_USER=u -e POSTGRES_PASSWORD=p \
  -e DATABASE_URL=postgresql://u:p@127.0.0.1:1/x -e SQLALCHEMY_DATABASE_URI=postgresql://u:p@127.0.0.1:1/x \
  -e DEFAULT_SECRET_KEY=sweep-default-key-0123456789abcdef -e JWT_SECRET_KEY=sweep-jwt-key-fedcba9876543210 \
  -e PYTHONPATH=/zenysis -e ZEN_HOME=/zenysis -e R77_SRC_ROOT=/zenysis -e ZEN_OFFLINE=1 \
  "$IMG" /sweep.py config data db log models util web pipeline scripts 2>/dev/null </dev/null \
  | grep -P '\t' | LC_ALL=C sort > "$OUT"
cut -f2 "$OUT" | cut -c1-3 | sort | uniq -c
