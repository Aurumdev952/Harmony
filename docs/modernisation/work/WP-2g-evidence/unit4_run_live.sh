#!/usr/bin/env bash
# Start gunicorn (gevent, 2 workers) with the WP-2g log config, fire concurrent
# requests, check the lines, stop gunicorn.
set -u
WT=$(cd "$(dirname "$0")/../../../.." && pwd)
HERE="$WT/docs/modernisation/work/WP-2g-evidence"
OUT=${OUT:-/tmp/wp2g}
mkdir -p "$OUT"
cd "$WT"
PORT=18742
LOG="$OUT/gunicorn_live.jsonl"
: > "$LOG"
RUN=(uv run --with 'gunicorn[gevent]==20.0.4' --with 'setuptools<70')
env LOG_FORMAT=json LOG_STREAM=stdout ZEN_ENV=rw PYTHONPATH="$WT" \
  "${RUN[@]}" python "$HERE/unit4_live_app.py" "127.0.0.1:$PORT" > "$LOG" 2>"$OUT/gunicorn_stderr.txt" &
PID=$!
for _ in $(seq 50); do
  curl -sf "http://127.0.0.1:$PORT/work/1" >/dev/null && break
  sleep 0.2
done
"${RUN[@]}" python "$HERE/unit4_fire.py" "http://127.0.0.1:$PORT" "$LOG"
STATUS=$?
kill -TERM "$PID"
wait "$PID" 2>/dev/null
echo "stderr bytes: $(wc -c < "$OUT/gunicorn_stderr.txt")"
exit $STATUS
