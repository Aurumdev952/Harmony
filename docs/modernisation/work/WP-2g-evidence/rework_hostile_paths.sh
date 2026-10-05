#!/usr/bin/env bash
# Start the unit 4 gunicorn app and time hostile paths (rework_hostile_paths.py).
# LOG_PACKAGE_ROOT, when set, is put first on PYTHONPATH, so a directory holding
# an older `log/` package runs the same requests for a before/after comparison.
set -u
WT=$(cd "$(dirname "$0")/../../../.." && pwd)
HERE="$WT/docs/modernisation/work/WP-2g-evidence"
OUT=${OUT:-/tmp/wp2g-hostile}
mkdir -p "$OUT"
cd "$WT" || exit 1
PORT=18743
RUN=(uv run --with 'gunicorn[gevent]==20.0.4' --with 'setuptools<70')
env LOG_FORMAT=json LOG_STREAM=stdout ZEN_ENV=rw \
  PYTHONPATH="${LOG_PACKAGE_ROOT:+$LOG_PACKAGE_ROOT:}$WT" \
  "${RUN[@]}" python "$HERE/unit4_live_app.py" "127.0.0.1:$PORT" \
  > "$OUT/stdout.jsonl" 2> "$OUT/stderr.txt" &
PID=$!
for _ in $(seq 50); do
  curl -sf "http://127.0.0.1:$PORT/work/1" > /dev/null && break
  sleep 0.2
done
"${RUN[@]}" python "$HERE/rework_hostile_paths.py" "http://127.0.0.1:$PORT"
kill -TERM "$PID"
wait "$PID" 2> /dev/null
echo "access lines: $(grep -c '"gunicorn.access"' "$OUT/stdout.jsonl"), stderr bytes: $(wc -c < "$OUT/stderr.txt")"
