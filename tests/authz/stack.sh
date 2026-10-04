#!/bin/bash
# Runs a private copy of the WP-2c contract stack (tests/contract/stack) for the
# HTTP layer of the authorisation suite, under its own project name and port so
# it never shares a database with the contract recorder.
#
#   tests/authz/stack.sh up      # start, migrate, seed the admin, wait for web
#   tests/authz/stack.sh env     # print the env tests/authz/http needs
#   tests/authz/stack.sh down    # stop and delete containers and tmpfs data
#
# The admin password is generated per stack into a mode-600 file outside the
# repository (SPEC INV-6).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
STACK="${HERE}/../contract/stack"
export CONTRACT_PROJECT="${AUTHZ_PROJECT:-harmony-wp2b-authz}"
export CONTRACT_WEB_PORT="${AUTHZ_WEB_PORT:-58660}"
export CONTRACT_USERNAME="${AUTHZ_ADMIN_USERNAME:-authz-admin@harmony.invalid}"
CREDENTIALS="${XDG_RUNTIME_DIR:-/tmp}/${CONTRACT_PROJECT}.env"

if [[ ! -f "${STACK}/compose.yaml" ]]; then
  echo "authz stack: ${STACK}/compose.yaml is missing; it arrives with WP-2c" >&2
  exit 2
fi

if [[ ! -f "${CREDENTIALS}" ]]; then
  umask 077
  printf 'CONTRACT_PASSWORD=%s\n' "$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" > "${CREDENTIALS}"
fi
# shellcheck disable=SC1090
source "${CREDENTIALS}"
export CONTRACT_PASSWORD

compose() {
  docker compose -p "${CONTRACT_PROJECT}" -f "${STACK}/compose.yaml" "$@"
}

case "${1:-}" in
  up)
    compose up -d --no-build --wait postgres redis druid-stub mailpit
    compose up -d --no-build web hasura
    for _ in $(seq 1 120); do
      if curl -fsS -o /dev/null "http://127.0.0.1:${CONTRACT_WEB_PORT}/login"; then
        echo "authz stack: web is up at http://127.0.0.1:${CONTRACT_WEB_PORT}"
        exit 0
      fi
      sleep 5
    done
    echo 'authz stack: web did not become ready; see `stack.sh logs`' >&2
    exit 1
    ;;
  down)
    compose down --volumes --remove-orphans
    rm -f "${CREDENTIALS}"
    ;;
  logs)
    compose logs --tail 200 "${@:2}"
    ;;
  psql)
    compose exec -T postgres psql -U postgres -d harmony_demo-local "${@:2}"
    ;;
  env)
    echo "export AUTHZ_BASE_URL=http://127.0.0.1:${CONTRACT_WEB_PORT}"
    echo "export AUTHZ_ADMIN_USERNAME=${CONTRACT_USERNAME}"
    echo "export AUTHZ_CREDENTIALS_FILE=${CREDENTIALS}"
    ;;
  *)
    echo "usage: $0 up|down|logs|psql|env" >&2
    exit 2
    ;;
esac
