#!/bin/bash
# Runs the Playwright suite against a disposable harmony_demo stack.
#
#   e2e/run.sh [playwright args]   build the client if needed, bring the stack
#                                  up, run the projects in order (visual,
#                                  a11y, e2e), always take it down; with
#                                  arguments (e.g. --grep @smoke) only a11y
#                                  and e2e run, each passing if it has no
#                                  matching test
#   e2e/run.sh up | down           manage the stack for an iterating session;
#                                  `up` prints the commands to run, in order
#   e2e/run.sh visual [args]       run one project on a stack that is up;
#   e2e/run.sh a11y [args]         visual and a11y need the stack as seeded,
#   e2e/run.sh e2e [args]          so run them before e2e, and after an e2e
#                                  run start a new stack (down, then up)
#                                  (visual --update-snapshots rewrites
#                                  e2e/visual/)
#   e2e/run.sh client              rebuild the client if its sources changed
#   e2e/run.sh build               rebuild the production client bundles
#
# The stack is WP-2c's tests/contract/stack (internal network, generated
# secrets, seeded site admin, mail sink) with its Druid stub swapped for a
# deterministic broker and a stand-in renderer (stack/compose.e2e.yaml),
# plus one container that serves the production client build where Flask's
# dev proxy expects webpack.
#
# The browser suite runs on this machine's Playwright. The visual suite runs
# in the pinned Playwright image, because pixels depend on the fonts and
# libraries that render them; its tag must match @playwright/test in
# e2e/package.json.
#
# Concurrent runs need their own E2E_PROJECT and E2E_WEB_PORT.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
export CONTRACT_PROJECT="${E2E_PROJECT:-harmony-wp2e-e2e}"
export CONTRACT_WEB_PORT="${E2E_WEB_PORT:-58670}"
export CONTRACT_USERNAME="${E2E_USERNAME:-e2e-admin@harmony.invalid}"
# Real Druid client on a deterministic broker, and a stand-in renderer.
export CONTRACT_OVERLAYS="${ROOT}/e2e/stack/compose.e2e.yaml"
STACK="${ROOT}/tests/contract/stack/stack.sh"
ASSETS="${CONTRACT_PROJECT}-assets"
# Same image and digest as the stack's druid-stub and forwarder.
PYTHON_IMAGE="python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
# mcr.microsoft.com/playwright:v1.56.1-noble
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright@sha256:f1e7e01021efd65dd1a2c56064be399f3e4de00fd021ac561325f2bfbb2b837a"
# The web-client image's base (docker/web/Dockerfile_web-client): the client
# builds on Node 18.17, and its native packages do not compile on newer Nodes.
NODE_IMAGE="node:18.17.1-bookworm@sha256:933bcfad91e9052a02bc29eb5aa29033e542afac4174f9524b79066d97b23c24"

# Under rootless Docker a container's root is the calling user; elsewhere
# containers run as the caller, so files they write or read keep their owner.
DOCKER_USER=()
if ! docker info --format '{{.SecurityOptions}}' | grep -q rootless; then
  DOCKER_USER=(--user "$(id -u):$(id -g)")
fi

# Everything the build reads, relative to the repository: webpack's inputs
# and relay.config.js, which babel-plugin-relay loads.
CLIENT_SOURCES=(web/client web/public/scss web/public/images web/public/fonts web/public/js
  web/webpack.prod.config.js relay.config.js package.json yarn.lock)
CLIENT_BUNDLES=web/public/build/min
# Written next to the bundles by build_client only: a hash of what the build
# read (the sources and the image that built them) and of what it wrote.
CLIENT_STAMP="${ROOT}/web/public/build/e2e-client.stamp"

# Content hashes, so an uncommitted edit counts as a change and no git
# checkout is needed.
files_hash() {
  (cd "${ROOT}" && find "$@" -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum)
}

client_sources_hash() {
  { echo "${NODE_IMAGE}"; files_hash "${CLIENT_SOURCES[@]}"; } | sha256sum | cut -c1-64
}

client_bundles_hash() {
  files_hash "${CLIENT_BUNDLES}" | sha256sum | cut -c1-64
}

build_client() {
  local sources
  sources="$(client_sources_hash)"
  # A build that fails or is interrupted leaves no stamp, so the next run
  # builds again.
  rm -f "${CLIENT_STAMP}"
  docker run --rm "${DOCKER_USER[@]}" \
    -v "${ROOT}:/src" -w /src -e HOME=/tmp \
    "${NODE_IMAGE}" sh -c 'yarn install --frozen-lockfile && yarn build'
  printf 'sources %s\nbundles %s\n' "${sources}" "$(client_bundles_hash)" >"${CLIENT_STAMP}"
}

ensure_playwright() {
  if [[ ! -x "${ROOT}/e2e/node_modules/.bin/playwright" ]]; then
    (cd "${ROOT}/e2e" && yarn install --frozen-lockfile)
  fi
  # The a11y and e2e projects run on this machine's Chromium; a no-op once
  # the pinned Playwright's build is in its cache. CI runners also need
  # `playwright install-deps chromium` once.
  "${ROOT}/e2e/node_modules/.bin/playwright" install chromium
}

# Serving bundles older than the sources, or bundles built some other way,
# would test the wrong client, so any difference from the stamp rebuilds.
ensure_client() {
  if [[ -f "${CLIENT_STAMP}" && -f "${ROOT}/${CLIENT_BUNDLES}/sourcemap.json" ]] &&
    [[ "$(cat "${CLIENT_STAMP}")" == "$(printf 'sources %s\nbundles %s' \
      "$(client_sources_hash)" "$(client_bundles_hash)")" ]]; then
    echo "e2e: client build matches its sources"
    return
  fi
  echo "e2e: no client build from these sources by run.sh; building"
  build_client
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
  # Mount point for the web container's upload tmpfs (ignored by the repo).
  mkdir -p "${ROOT}/uploads"
  "${STACK}" up
  start_assets
  seed_catalog
}

# The seeded admin's signed-in browser state (its session cookie) sits next
# to the stack's credentials file, in the same 0700 runtime directory, and
# goes with the stack.
admin_state_file() {
  echo "$(dirname "${CONTRACT_CREDENTIALS_FILE}")/${CONTRACT_PROJECT}-admin-state.json"
}

stack_down() {
  docker rm -f "${ASSETS}" >/dev/null 2>&1 || true
  eval "$("${STACK}" env)"
  rm -f "$(admin_state_file)"
  "${STACK}" down
}

export_env() {
  eval "$("${STACK}" env)"
  export E2E_BASE_URL="${CONTRACT_BASE_URL}"
  export E2E_USERNAME="${CONTRACT_USERNAME}"
  export E2E_CREDENTIALS_FILE="${CONTRACT_CREDENTIALS_FILE}"
  export E2E_PROJECT="${CONTRACT_PROJECT}"
  E2E_ADMIN_STATE="$(admin_state_file)"
  export E2E_ADMIN_STATE
}

run_project() {
  (cd "${ROOT}/e2e" && E2E_RUN="$1" node_modules/.bin/playwright test --project "$1" "${@:2}")
}

# The image's browser reaches the stack through the forwarder's network
# namespace, as 127.0.0.1:5000.
run_visual() {
  docker run --rm "${DOCKER_USER[@]}" \
    --network "container:$(container_of forward)" --shm-size 1g \
    -v "${ROOT}/e2e:/e2e" \
    -v "${E2E_CREDENTIALS_FILE}:/run/e2e/credentials.env:ro" \
    -w /e2e \
    -e HOME=/tmp \
    -e E2E_RUN=visual \
    -e E2E_BASE_URL=http://127.0.0.1:5000 \
    -e E2E_USERNAME="${E2E_USERNAME}" \
    -e E2E_PROJECT="${E2E_PROJECT}" \
    -e E2E_CREDENTIALS_FILE=/run/e2e/credentials.env \
    -e E2E_ADMIN_STATE=/tmp/admin-state.json \
    -e E2E_VISUAL_IMAGE="${PLAYWRIGHT_IMAGE}" \
    "${PLAYWRIGHT_IMAGE}" node_modules/.bin/playwright test --project visual "$@"
}

case "${1:-}" in
  up)
    stack_up
    export_env
    echo "e2e: stack up. Run the projects one at a time, in this order:"
    echo "  e2e/run.sh visual   # needs the stack as seeded"
    echo "  e2e/run.sh a11y     # needs the stack as seeded"
    echo "  e2e/run.sh e2e      # adds dashboards, users and sources"
    echo "After an e2e run, visual and a11y need a new stack (e2e/run.sh down, then up)."
    ;;
  down)
    stack_down
    ;;
  visual)
    ensure_playwright
    export_env
    run_visual "${@:2}"
    ;;
  a11y | e2e)
    ensure_playwright
    export_env
    run_project "$1" "${@:2}"
    ;;
  client)
    ensure_client
    ;;
  build)
    build_client
    ;;
  *)
    ensure_playwright
    trap stack_down EXIT
    stack_up
    export_env
    # Visual and a11y go first: both expect the stack as seeded, before the
    # e2e project adds dashboards, users, sources and views.
    status=0
    if [[ $# -gt 0 ]]; then
      run_project a11y --pass-with-no-tests "$@" || status=$?
      run_project e2e --pass-with-no-tests "$@" || status=$?
    else
      run_visual || status=$?
      run_project a11y || status=$?
      run_project e2e || status=$?
    fi
    exit "${status}"
    ;;
esac
