#!/bin/bash
# flask_db_check.sh <repo-tree> <python>: `flask db upgrade` then `flask db current` on a
# throwaway Postgres, with a Druid coordinator stub answering [] (seed 93bb8d693499).
# Logs go to a fresh temporary directory, printed at the end.
set -uo pipefail
TREE="$1"
PYTHON="$2"
PG="wp3b-pg-$$"
DRUID="wp3b-druid-$$"
DRUID_IP=127.0.83.1
LOGS=$(mktemp -d)
cleanup() { docker stop "$PG" "$DRUID" > /dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --rm --name "$PG" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=zenysis \
  postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81 > /dev/null
docker run -d --rm --name "$DRUID" -p "${DRUID_IP}:8081:8081" \
  python:3.13.16-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed python -c '
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
sleep 1

cd "$TREE"
run() {
  env -i PATH="$PATH" PYTHONPATH=. FLASK_APP=web.server.app ZEN_OFFLINE=1 \
    ZEN_ENV=harmony_demo DEFAULT_SECRET_KEY=scratch-default-0123456789 JWT_SECRET_KEY=scratch-jwt-9876543210 \
    DRUID_HOST="http://${DRUID_IP}" \
    DATABASE_URL="postgresql://postgres:scratch@127.0.0.1:${PORT}/zenysis" \
    "$PYTHON" -m flask db "$@"
}
"$PYTHON" -c 'import sys, flask_migrate, alembic; print(sys.version.split()[0], "Flask-Migrate", flask_migrate.__version__ if hasattr(flask_migrate, "__version__") else "?", "alembic", alembic.__version__)'
run upgrade > "$LOGS"/flaskdb-upgrade.log 2>&1
echo "flask db upgrade: exit $? ($(wc -l < "$LOGS"/flaskdb-upgrade.log) log lines)"
echo "alembic_version: $(docker exec "$PG" psql -U postgres -d zenysis -tAc 'SELECT version_num FROM alembic_version')"
run current > "$LOGS"/flaskdb-current.log 2>&1
echo "flask db current: exit $?"
tail -3 "$LOGS"/flaskdb-current.log
echo "logs: $LOGS"
