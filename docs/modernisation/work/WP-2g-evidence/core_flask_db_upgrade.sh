#!/bin/bash
# `flask db upgrade` from an empty throwaway Postgres, as initialize_new_container.sh
# runs it, with LOG_FORMAT=json. Seed 93bb8d693499 asks the Druid coordinator (port
# 8081) for datasources, so a stub container answers `[]` to every request and the
# seed takes its "no datasource" branch. Prints the raw stdout and stderr, then a
# summary that counts the lines on each stream that are not JSON.
# Usage: core_flask_db_upgrade.sh <python with requirements-web installed> [LOG_LEVEL]
set -euo pipefail

PYTHON="$1"
LEVEL="${2:-INFO}"
PG="core-wp2g-pg-$$"
DRUID="core-wp2g-druid-$$"
REPO_ROOT=$(cd "$(dirname "$0")/../../../.." && pwd -P)
OUT=$(mktemp)
ERR=$(mktemp)
# The coordinator URL always carries :8081, so the stub takes that port on a spare
# loopback address.
DRUID_IP=127.0.82.1

cleanup() {
  docker stop "$PG" "$DRUID" > /dev/null 2>&1 || true
  rm -f "$OUT" "$ERR"
}
trap cleanup EXIT

docker run -d --rm --name "$PG" -p 127.0.0.1::5432 \
  -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=zenysis postgres:15.2-alpine > /dev/null
docker run -d --rm --name "$DRUID" -p "${DRUID_IP}:8081:8081" python:3.12-slim python -c '
import http.server
class Empty(http.server.BaseHTTPRequestHandler):
    def reply(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"[]")
    do_GET = do_POST = reply
http.server.HTTPServer(("0.0.0.0", 8081), Empty).serve_forever()
' > /dev/null
PORT=$(docker port "$PG" 5432/tcp | head -1 | cut -d: -f2)
until docker exec "$PG" pg_isready -U postgres -d zenysis -h 127.0.0.1 -q; do sleep 0.5; done

cd "$REPO_ROOT"
status=0
env -i PATH="$PATH" PYTHONPATH=. FLASK_APP=web.server.app ZEN_OFFLINE=1 \
  ZEN_ENV=harmony_demo DEFAULT_SECRET_KEY=scratch DRUID_HOST="http://${DRUID_IP}" \
  DATABASE_URL="postgresql://postgres:scratch@127.0.0.1:${PORT}/zenysis" \
  LOG_FORMAT=json LOG_LEVEL="$LEVEL" \
  "$PYTHON" -m flask db upgrade 2> "$ERR" > "$OUT" || status=$?
echo "--- stdout"
cat "$OUT"
echo "--- stderr"
cat "$ERR"
echo "--- exit: $status," \
  "stdout lines: $(wc -l < "$OUT"), non-JSON: $(grep -cv '^{' "$OUT" || true);" \
  "stderr lines: $(wc -l < "$ERR")," \
  "non-JSON: $(grep -cv '^{' "$ERR" || true)," \
  "alembic.runtime.migration: $(grep -c '"logger": "alembic.runtime.migration"' "$ERR" || true)," \
  "version: $(docker exec "$PG" psql -U postgres -d zenysis -tAc 'SELECT version_num FROM alembic_version')"
