#!/bin/bash
# Runs the Playwright suite against a disposable harmony_demo stack.
#
#   e2e/run.sh [playwright args]   build the client if needed, bring the stack
#                                  up, run the suite, always take it down
#   e2e/run.sh up | down           manage the stack for an iterating session;
#                                  `up` prints the playwright command to run
#   e2e/run.sh build               rebuild the production client bundles
#
# The stack is WP-2c's tests/contract/stack (internal network, generated
# secrets, seeded site admin, Druid stub, mail sink) plus one container that
# serves the production client build where Flask's dev proxy expects webpack.
#
# Concurrent runs need their own E2E_PROJECT and E2E_WEB_PORT.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
export CONTRACT_PROJECT="${E2E_PROJECT:-harmony-wp2e-e2e}"
export CONTRACT_WEB_PORT="${E2E_WEB_PORT:-58670}"
export CONTRACT_USERNAME="${E2E_USERNAME:-e2e-admin@harmony.invalid}"
STACK="${ROOT}/tests/contract/stack/stack.sh"
ASSETS="${CONTRACT_PROJECT}-assets"
# Same image and digest as the stack's druid-stub and forwarder.
PYTHON_IMAGE="python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"

build_client() {
  (cd "${ROOT}" && yarn build)
}

ensure_playwright() {
  if [[ ! -x "${ROOT}/e2e/node_modules/.bin/playwright" ]]; then
    (cd "${ROOT}/e2e" && yarn install --frozen-lockfile)
  fi
}

ensure_client() {
  if [[ ! -f "${ROOT}/web/public/build/min/sourcemap.json" ]]; then
    build_client
  fi
}

container_of() {
  local id
  id="$(docker ps -q \
    --filter "label=com.docker.compose.project=${CONTRACT_PROJECT}" \
    --filter "label=com.docker.compose.service=$1")"
  if [[ -z "${id}" ]]; then
    echo "e2e: no $1 container in ${CONTRACT_PROJECT}" >&2
    return 1
  fi
  echo "${id}"
}

start_assets() {
  local web
  web="$(container_of web)"
  docker rm -f "${ASSETS}" >/dev/null 2>&1 || true
  docker run -d --name "${ASSETS}" \
    --label "com.harmony.e2e.project=${CONTRACT_PROJECT}" \
    --network "container:${web}" \
    -v "${ROOT}/web/public:/public:ro" \
    -v "${ROOT}/e2e/stack/assets.py:/assets.py:ro" \
    "${PYTHON_IMAGE}" python -u /assets.py /public >/dev/null
}

# The contract stack has users but an empty Data Catalog, and the query tool
# refuses to start without indicators. Load harmony_demo's config into it the
# way a deployment does, then add the e2e-only rows.
seed_catalog() {
  docker exec "$(container_of web)" \
    python scripts/data_catalog/populate_query_models_from_config.py >/dev/null 2>&1
  docker exec -i "$(container_of postgres)" \
    psql -q -v ON_ERROR_STOP=1 -U postgres -d harmony_demo-local <"${ROOT}/e2e/stack/seed.sql"
}

stack_up() {
  ensure_client
  "${STACK}" up
  start_assets
  seed_catalog
}

stack_down() {
  docker rm -f "${ASSETS}" >/dev/null 2>&1 || true
  "${STACK}" down
}

export_env() {
  eval "$("${STACK}" env)"
  export E2E_BASE_URL="${CONTRACT_BASE_URL}"
  export E2E_USERNAME="${CONTRACT_USERNAME}"
  export E2E_CREDENTIALS_FILE="${CONTRACT_CREDENTIALS_FILE}"
  export E2E_PROJECT="${CONTRACT_PROJECT}"
}

case "${1:-}" in
  up)
    stack_up
    export_env
    echo "e2e: stack up. From e2e/, run:"
    echo "  E2E_BASE_URL=${E2E_BASE_URL} E2E_USERNAME=${E2E_USERNAME} E2E_PROJECT=${E2E_PROJECT} E2E_CREDENTIALS_FILE=${E2E_CREDENTIALS_FILE} node_modules/.bin/playwright test"
    ;;
  down)
    stack_down
    ;;
  build)
    build_client
    ;;
  *)
    ensure_playwright
    trap stack_down EXIT
    stack_up
    export_env
    cd "${ROOT}/e2e"
    node_modules/.bin/playwright test "$@"
    ;;
esac
