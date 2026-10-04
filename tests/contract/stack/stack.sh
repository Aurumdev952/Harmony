#!/bin/bash
# Bring the contract stack up or down.
#
#   tests/contract/stack/stack.sh up     # build if needed, start, seed, wait for web
#   tests/contract/stack/stack.sh down   # stop and delete containers and tmpfs data
#   tests/contract/stack/stack.sh env    # print the env the recorder and replay need
#
# The admin password is generated per stack and kept in a mode-600 file outside
# the repository, so it never lands in fixtures, logs or git (SPEC INV-6).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
export CONTRACT_PROJECT="${CONTRACT_PROJECT:-harmony-wp2c-contract}"
export CONTRACT_WEB_PORT="${CONTRACT_WEB_PORT:-58650}"
export CONTRACT_USERNAME="${CONTRACT_USERNAME:-contract-admin@harmony.invalid}"
CREDENTIALS="${XDG_RUNTIME_DIR:-/tmp}/${CONTRACT_PROJECT}.env"

compose() {
  docker compose -p "${CONTRACT_PROJECT}" -f "${HERE}/compose.yaml" "$@"
}

load_password() {
  if [[ -z "${CONTRACT_PASSWORD:-}" ]]; then
    if [[ ! -f "${CREDENTIALS}" ]]; then
      umask 077
      printf 'CONTRACT_PASSWORD=%s\n' "$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" > "${CREDENTIALS}"
    fi
    # shellcheck disable=SC1090
    source "${CREDENTIALS}"
  fi
  export CONTRACT_PASSWORD
}

wait_for_web() {
  local url="http://127.0.0.1:${CONTRACT_WEB_PORT}/login"
  for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null "${url}"; then
      echo "contract stack: web is up at http://127.0.0.1:${CONTRACT_WEB_PORT}"
      return 0
    fi
    sleep 5
  done
  echo 'contract stack: web did not become ready; see `stack.sh logs`' >&2
  return 1
}

apply_hasura_metadata() {
  for _ in $(seq 1 60); do
    if compose exec -T hasura sh -c 'exec 3<>/dev/tcp/127.0.0.1/8080' 2>/dev/null \
      || compose exec -T web python -c "import requests; requests.get('http://hasura:8080/healthz', timeout=2).raise_for_status()" 2>/dev/null; then
      compose exec -T web python scripts/db/hasura/apply_metadata_snapshot.py --hasura_host http://hasura:8080
      return 0
    fi
    sleep 2
  done
  echo 'contract stack: hasura did not become ready; GraphQL cases will fail' >&2
  return 1
}

case "${1:-}" in
  up)
    load_password
    if ! docker image inspect harmony-wp2c-web-server:base >/dev/null 2>&1; then
      docker build --platform linux/amd64 -f "${HERE}/../../../docker/web/Dockerfile_web-server" \
        -t harmony-wp2c-web-server:base "${HERE}/../../.."
    fi
    compose build web-init
    compose up -d --wait postgres redis druid-stub mailpit
    compose up -d web hasura
    wait_for_web
    apply_hasura_metadata
    ;;
  down)
    compose down --volumes --remove-orphans
    rm -f "${CREDENTIALS}"
    ;;
  logs)
    compose logs --tail 200 "${@:2}"
    ;;
  env)
    load_password
    echo "export CONTRACT_BASE_URL=http://127.0.0.1:${CONTRACT_WEB_PORT}"
    echo "export CONTRACT_USERNAME=${CONTRACT_USERNAME}"
    echo "export CONTRACT_CREDENTIALS_FILE=${CREDENTIALS}"
    ;;
  *)
    echo "usage: $0 up|down|logs|env" >&2
    exit 2
    ;;
esac
