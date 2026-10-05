#!/usr/bin/env bash
# WP-3b unit 5: `make dev-prepare-database` and `make up DEV=1`, as the Makefile runs
# them, on this branch's dev image in a throwaway project. Usage: run.sh up | probe | down
set -uo pipefail
TREE=$(cd "$(dirname "$0")/../../../../.." && pwd -P)
S=${WORK:-/tmp/wp3b-dev}
mkdir -p "$S"
P=wp3b-infra3-dev
ENV_FILE=$S/dev.env
sed -e "s|^STACK_DIR=.*|STACK_DIR=$TREE/docs/modernisation/work/WP-3b-evidence/web_stack|" \
  -e "s|^MC_CONFIG_PATH=.*|MC_CONFIG_PATH=$S/mc|" \
  "$TREE/docs/modernisation/work/WP-3b-evidence/web_stack/stack.env" > "$ENV_FILE"
mkdir -p "$S/mc"
compose() {
  docker compose -p "$P" --project-directory "$TREE" --env-file "$ENV_FILE" \
    -f "$TREE/docker-compose.yaml" -f "$TREE/docker-compose.dev.yaml" -f "$(dirname "$0")/overlay.yaml" "$@"
}
case "$1" in
up)
  compose up -d --wait postgres
  # init-db's upgrade_dev_database.sh calls `git rev-parse --show-toplevel`, which
  # fails in a git worktree mounted without its main repository, so its two steps
  # run directly: create the database, then the same `flask db upgrade`.
  echo "== dev database (upgrade_dev_database.sh's steps)"
  compose exec -T postgres psql -U postgres -tAc 'CREATE DATABASE "harmony_demo-local"'
  compose run --rm -T web /bin/bash -c "source venv/bin/activate && DATABASE_URL=postgresql://postgres:zenysis@postgres/harmony_demo-local FLASK_APP=web.server.app_base ZEN_ENV=harmony_demo flask db upgrade" 2>&1 | grep -E 'Running upgrade|Error|Traceback' | tail -3
  echo "== make up DEV=1 (web)"
  compose up -d --wait --wait-timeout 900 redis hasura web
  echo "up: exit $?"
  compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
  ;;
probe)
  compose exec -T web /bin/bash -c 'source venv/bin/activate; python -c "import sys; print(sys.version.split()[0], sys.executable)"; for p in / /login /api2/user; do python -c "import urllib.request, urllib.error
try:
    print(\"$p\", urllib.request.urlopen(\"http://127.0.0.1:5000$p\", timeout=60).status)
except urllib.error.HTTPError as e:
    print(\"$p\", e.code)"; done'
  compose logs --no-color web 2>&1 | grep -E 'Traceback|Error|Running on|webpack .* compiled' | cut -c1-160 | sort | uniq -c | head
  ;;
down)
  compose --profile donotstart down --remove-orphans
  ;;
esac
