#!/usr/bin/env bash
# docker compose config --quiet for the base file with each overlay the Makefile and
# docs combine, plus the standalone files, with dummy values (never the repo .env).
HERE=$(cd "$(dirname "$0")" && pwd -P)
cd "$HERE/../../../.." || exit 1
ENV="$HERE/web_stack/stack.env"
ERR=$(mktemp)
fail=0
check() {
  if docker compose --env-file "$ENV" "$@" config --quiet 2>"$ERR"; then
    echo "OK   $*"
  else
    echo "FAIL $*"; grep -v 'level=warning' "$ERR" | head -3; fail=1
  fi
}
check -f docker-compose.yaml
check -f docker-compose.yaml -f docker-compose.prod.yaml
check -f docker-compose.yaml -f docker-compose.local.yaml
check -f docker-compose.yaml -f docker-compose.dev.yaml
check -f docker-compose.yaml -f docker-compose.db.yaml -f docker-compose.local.yaml
check -f docker-compose.yaml -f docker-compose.db.yaml -f docker-compose.prod.yaml
check -f docker-compose.db.yaml
check -f docker-compose.pipeline.yaml
check -f docker-compose.build.yaml
exit $fail
