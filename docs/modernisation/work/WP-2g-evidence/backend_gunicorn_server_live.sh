#!/usr/bin/env bash
# Start web/gunicorn_server.py with a stub app (1 gevent worker), send two requests
# (one with a query token), stop it, print what it logged.
# Needs REQS: the py3.8 web requirements rewritten as in WP-0c "How to run the tests".
# Baseline: pass the pre-change server file as $1 (git show c39ab23:web/gunicorn_server.py).
set -u
WT=$(cd "$(dirname "$0")/../../../.." && pwd)
HERE="$WT/docs/modernisation/work/WP-2g-evidence"
REQS=${REQS:-/tmp/reqs.txt}
OUT=${OUT:-/tmp/wp2g_be_live}
mkdir -p "$OUT"
cd "$WT"
PORT=18761
env LOG_FORMAT=json LOG_STREAM=stdout ZEN_ENV=rw PYTHONPATH="$WT" \
  uv run --no-project -p 3.8 --with-requirements "$REQS" \
  python "$HERE/backend_gunicorn_server_live.py" "$PORT" "$@" \
  > "$OUT/stdout.jsonl" 2> "$OUT/stderr.txt" &
PID=$!
for _ in $(seq 100); do
  curl -sf "http://127.0.0.1:$PORT/ping" > /dev/null && break
  sleep 0.2
done
curl -s -D - -o /dev/null "http://127.0.0.1:$PORT/ping?token=secret123" | grep -i x-request-id
sleep 0.5
kill -TERM "$PID"
wait "$PID" 2> /dev/null
echo "--- stdout"
cat "$OUT/stdout.jsonl"
echo "--- stderr"
cat "$OUT/stderr.txt"
