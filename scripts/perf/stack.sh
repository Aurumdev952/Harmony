#!/bin/bash
# The performance-baseline stack: Druid 0.23 from druid_setup/single, loaded with
# the synthetic harmony_demo dataset, and the web app pointed at it.
#
#   scripts/perf/stack.sh dataset   # generate the CSV, run process_csv and fill_dimension_data
#   scripts/perf/stack.sh up        # build web, start Druid, index the dataset if Druid has none, start web
#   scripts/perf/stack.sh index [--force]   # re-index, register the datasource with web, restart web
#   scripts/perf/stack.sh ui        # build the production client if it changed; serve it on PERF_UI_PORT
#   scripts/perf/stack.sh reference <git ref>   # start that commit beside this checkout, for paired runs
#   scripts/perf/stack.sh stop      # stop every container; keep volumes, scratch and secrets
#   scripts/perf/stack.sh down      # stop everything, delete volumes, scratch and secrets
#   scripts/perf/stack.sh env       # what baseline.py and dashboards.mjs read
#   scripts/perf/stack.sh logs druid|web [service]
#   scripts/perf/stack.sh config druid|web   # the merged Compose file
#
# Concurrent stacks need their own PERF_PROJECT and ports:
#   PERF_PROJECT          default harmony-wp1a-perf (Compose projects <name>-druid, <name>-web)
#   PERF_WEB_PORT         default 58700, PERF_UI_PORT 58701 (nginx in front of web)
#   PERF_REFERENCE_WEB_PORT default 58702, PERF_REFERENCE_UI_PORT 58703 (the reference copy)
#   PERF_COORDINATOR_PORT default 58981, PERF_BROKER_PORT 58982, PERF_ROUTER_PORT 58988
#   PERF_SCRATCH          default ${TMPDIR:-/tmp}/<project>: dataset, pipeline output, broker request log
# Every port is published on 127.0.0.1 only. Secrets are generated per stack into a
# mode-600 file outside the repository (SPEC INV-6); compose reads no .env file.
# The file lives under XDG_STATE_HOME, not the tmpfs XDG_RUNTIME_DIR: Druid's
# containers and volumes survive a reboot, and its metadata database keeps the
# password it was created with.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "${HERE}/../.." && pwd -P)"
export PERF_PROJECT="${PERF_PROJECT:-harmony-wp1a-perf}"
export PERF_WEB_PORT="${PERF_WEB_PORT:-58700}"
export PERF_UI_PORT="${PERF_UI_PORT:-58701}"
export PERF_REFERENCE_WEB_PORT="${PERF_REFERENCE_WEB_PORT:-58702}"
export PERF_REFERENCE_UI_PORT="${PERF_REFERENCE_UI_PORT:-58703}"
export PERF_COORDINATOR_PORT="${PERF_COORDINATOR_PORT:-58981}"
export PERF_BROKER_PORT="${PERF_BROKER_PORT:-58982}"
export PERF_ROUTER_PORT="${PERF_ROUTER_PORT:-58988}"
export PERF_SCRATCH="${PERF_SCRATCH:-${TMPDIR:-/tmp}/${PERF_PROJECT}}"
export PERF_REQUEST_LOG_DIR="${PERF_SCRATCH}/broker-requests"
# `stack.sh reference` unpacks the reference commit here (src/, client/, sha).
export PERF_REFERENCE_DIR="${PERF_SCRATCH}/reference"
# Compose interpolates every service, so the reference image needs a value
# even when no reference runs.
export PERF_REFERENCE_IMAGE="${PERF_REFERENCE_IMAGE:-no-reference-image}"
export PERF_USERNAME="${PERF_USERNAME:-perf-admin@harmony.invalid}"
export PERF_REPO_ROOT="${ROOT}"
export PERF_STACK_DIR="${HERE}/stack"
# druid_setup/single requires a bind address; the overlay replaces its ports.
export DRUID_BIND_ADDRESS=127.0.0.1

SECRETS_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/harmony-perf"
SECRETS="${SECRETS_DIR}/${PERF_PROJECT}.env"
SECRET_NAMES=(PERF_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD HASURA_ADMIN_SECRET DEFAULT_SECRET_KEY JWT_SECRET_KEY DRUID_POSTGRES_PASSWORD)

DRUID_SERVICES=(postgres memcache zookeeper coordinator broker historical middlemanager router druid)

druid_compose() {
  docker compose -p "${PERF_PROJECT}-druid" --env-file /dev/null \
    --project-directory "${ROOT}/druid_setup/single" \
    -f "${ROOT}/druid_setup/single/docker-compose.yml" \
    -f "${HERE}/stack/druid.override.yaml" "$@"
}

web_compose() {
  docker compose -p "${PERF_PROJECT}-web" --env-file /dev/null \
    -f "${HERE}/stack/web.yaml" "$@"
}

new_secret() {
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

create_secrets() {
  if docker volume inspect "${PERF_PROJECT}-druid_metadata_data" >/dev/null 2>&1; then
    echo "perf stack: ${SECRETS} is missing but Druid's metadata volume exists;" \
      "new secrets would lock Druid out of it. Run stack.sh down to start over." >&2
    exit 1
  fi
  mkdir -p "${SECRETS_DIR}"
  chmod 700 "${SECRETS_DIR}"
  ( umask 077
    for name in "${SECRET_NAMES[@]}"; do
      printf '%s=%s\n' "${name}" "$(new_secret)"
    done > "${SECRETS}" )
}

# Read only the expected NAME=value lines; never source the file as shell.
load_secrets() {
  [[ -f "${SECRETS}" ]] || create_secrets
  local owner mode name value
  read -r owner mode < <(stat -c '%u %a' "${SECRETS}")
  if [[ "${owner}" != "$(id -u)" || "${mode}" != "600" ]]; then
    echo "perf stack: refusing ${SECRETS}: it must be owned by you with mode 600" >&2
    exit 1
  fi
  for name in "${SECRET_NAMES[@]}"; do
    value="$(grep -m1 "^${name}=[0-9a-f]\{64\}$" "${SECRETS}" | cut -d= -f2 || true)"
    if [[ -z "${value}" ]]; then
      echo "perf stack: ${SECRETS} has no valid ${name}; run stack.sh down" >&2
      exit 1
    fi
    export "${name}=${value}"
  done
  # Redis asks for a password only once the app sends one (WP-0b).
  if [[ -f "${ROOT}/web/server/configuration/redis_connection.py" ]]; then
    export PERF_REDIS_ARGS="--requirepass ${REDIS_PASSWORD}"
  fi
}

# Compose interpolates every variable even for down and logs.
placeholder_env() {
  export PERF_WEB_IMAGE="${PERF_WEB_IMAGE:-unused}"
  local name
  for name in "${SECRET_NAMES[@]}"; do
    export "${name}=${!name:-unused}"
  done
}

# image_tag <repo root>: the web image's inputs from that tree.
image_tag() {
  cat "$1/requirements.txt" "$1/requirements-web.txt" \
    "$1/docker/web/Dockerfile_web-server" "${HERE}/stack/Dockerfile" | sha256sum | cut -c1-12
}

# build_image <repo root>: build the web image of that tree; prints its name.
# The tag hashes every input the containers use from the image (the code is
# bind-mounted), so an existing tag is reused; PERF_REBUILD=1 rebuilds it.
# Each rebuild leaves about 2.4 GB of layers, and needs PyPI.
build_image() {
  local tag
  tag="$(image_tag "$1")"
  if [[ -z "${PERF_REBUILD:-}" ]] && docker image inspect "harmony-perf-web:${tag}" >/dev/null 2>&1; then
    echo "perf stack: reusing harmony-perf-web:${tag}" >&2
    echo "harmony-perf-web:${tag}"
    return 0
  fi
  docker build --platform linux/amd64 \
    -f "$1/docker/web/Dockerfile_web-server" \
    -t "harmony-perf-web-server:${tag}" "$1" >&2
  docker build --platform linux/amd64 \
    --build-arg "BASE_IMAGE=harmony-perf-web-server:${tag}" \
    -t "harmony-perf-web:${tag}" "${HERE}/stack" >&2
  echo "harmony-perf-web:${tag}"
}

build_images() {
  PERF_WEB_IMAGE="$(build_image "${ROOT}")"
  export PERF_WEB_IMAGE
}

use_built_image() {
  PERF_WEB_IMAGE="harmony-perf-web:$(image_tag "${ROOT}")"
  export PERF_WEB_IMAGE
}

# wait_for <description> <tries> <command...>: retry every 5 s.
wait_for() {
  local what="$1" tries="$2"
  shift 2
  for _ in $(seq 1 "${tries}"); do
    if "$@" >/dev/null 2>&1; then
      echo "perf stack: ${what}"
      return 0
    fi
    sleep 5
  done
  echo "perf stack: timed out waiting for ${what}" >&2
  return 1
}

coordinator() { curl -fsS "http://127.0.0.1:${PERF_COORDINATOR_PORT}$1"; }
broker() { curl -fsS "http://127.0.0.1:${PERF_BROKER_PORT}$1"; }

druid_jvms_running() {
  [[ -n "$(druid_compose ps -q --status running coordinator broker historical middlemanager router)" ]]
}

druid_ready() {
  coordinator /status/health | grep -q true &&
    broker /druid/broker/v1/readiness &&
    coordinator /druid/indexer/v1/workers | grep -q '"worker"' &&
    coordinator /druid/coordinator/v1/servers?simple | grep -q '"type":"historical"'
}

segments_loaded() {
  local status
  status="$(coordinator /druid/coordinator/v1/loadstatus)"
  grep -q '"harmony_demo_' <<<"${status}" && ! grep -o ':[0-9.]*' <<<"${status}" | grep -qv '^:100.0$'
}

broker_sees_datasource() {
  broker /druid/v2/datasources | grep -q '"harmony_demo_'
}

web_answers() {
  curl -fsS -o /dev/null "http://127.0.0.1:${PERF_WEB_PORT}/login"
}

ui_answers() {
  curl -fsS -o /dev/null "http://127.0.0.1:${PERF_UI_PORT}/build/dashboardBuilder.bundle.js"
}

# Rootless Docker frees a removed container's published port some seconds
# later, and nothing on the host shows when, so starting is retried. A failed
# start leaves a container without its port, so every try recreates them.
start_reference() {
  web_compose --profile reference up -d --no-deps --force-recreate web-reference ui-reference &&
    [[ -n "$(web_compose --profile reference port web-reference 5000)" ]] &&
    [[ -n "$(web_compose --profile reference port ui-reference 8080)" ]]
}

reference_answers() {
  curl -fsS -o /dev/null "http://127.0.0.1:${PERF_REFERENCE_WEB_PORT}/login" &&
    curl -fsS -o /dev/null "http://127.0.0.1:${PERF_REFERENCE_UI_PORT}/build/dashboardBuilder.bundle.js"
}

apply_hasura_metadata() {
  for _ in $(seq 1 60); do
    if web_compose exec -T web python -c "import requests; requests.get('http://hasura:8080/healthz', timeout=2).raise_for_status()" 2>/dev/null; then
      web_compose exec -T web python scripts/db/hasura/apply_metadata_snapshot.py --hasura_host http://hasura:8080
      return 0
    fi
    sleep 2
  done
  echo 'perf stack: hasura did not become ready' >&2
  return 1
}

# The two harmony_demo process steps the index step reads, with the arguments of
# pipeline/harmony_demo/process/run/00_yellow_fever/10_process and
# 90_shared/10_fill_dimension_data.abort_fail, on CPython 3.9 as in WP-2d's suite.
dataset() {
  local feed="${PERF_SCRATCH}/pipeline/feed" tmp="${PERF_SCRATCH}/pipeline/tmp"
  local out="${PERF_SCRATCH}/pipeline/out" bin="${PERF_SCRATCH}/bin"
  local static="${ROOT}/pipeline/harmony_demo/static_data"
  rm -rf "${PERF_SCRATCH}/pipeline"
  mkdir -p "${feed}" "${tmp}" "${out}" "${bin}"
  # gzip is a drop-in for the pigz flags the steps use (WP-2d's harness does the same).
  command -v pigz >/dev/null || ln -sf "$(command -v gzip)" "${bin}/pigz"
  uv run --no-project --python 3.9 python "${HERE}/dataset.py" "${feed}/yellow_fever_cases.csv" "$@"
  local py=(env -u PYTHONPATH ZEN_ENV=harmony_demo PYTHONPATH="${ROOT}" PIPELINE_SRC_ROOT="${ROOT}"
    PYTHONUTF8=1 LC_ALL=C.UTF-8 TZ=UTC PATH="${bin}:${PATH}"
    uv run --no-project --python 3.9 --with-requirements "${ROOT}/tests/pipeline/requirements.txt" python)
  ( cd "${tmp}"
    "${py[@]}" "${ROOT}/data/pipeline/scripts/process_csv.py" \
      --delimiter ';' \
      --rename_cols 'COD_MUN_LPI:MunicipalityName' 'SEXO:Sex' 'IDADE:Age' 'OBITO:Death' \
      --date 'DT_IS' \
      --prefix 'yellow_fever' \
      --sourcename 'yellow_fever' \
      --set_cols 'cases:1' 'test_indicator:5' \
      --fields 'cases' 'test_indicator' \
      --input="${feed}/yellow_fever_cases.csv" \
      --output_locations="${tmp}/locations.csv" \
      --output_fields="${tmp}/fields.csv" \
      --output_rows="${tmp}/processed_data.json.lz4"
    "${py[@]}" "${ROOT}/data/pipeline/scripts/fill_dimension_data.py" \
      --location_mapping_file="${static}/mapped_locations.csv" \
      --metadata_file="${static}/metadata_mapped.csv" \
      --input_file="${tmp}/processed_data.json.lz4" \
      --output_file_pattern="${out}/processed_rows.#.json.gz" \
      --shard_size=3000000 \
      --metadata_digest_file="${out}/metadata_digest_file.csv" )
  echo "perf stack: Druid rows: $(gzip -dc "${out}"/processed_rows.*.json.gz | wc -l)"
  echo "perf stack: digest:"
  cat "${out}/metadata_digest_file.csv"
}

index_druid() {
  [[ -n "$(ls "${PERF_SCRATCH}"/pipeline/out/processed_rows.*.json.gz 2>/dev/null)" ]] || dataset
  web_compose --profile index run --rm indexer "$@"
  wait_for 'every segment is loaded' 120 segments_loaded
  wait_for 'the broker serves the datasource' 60 broker_sees_datasource
}

# Migrations import config/harmony_demo/database.py, which asks Druid for the
# newest datasource, so Druid must hold one before web-init runs.
up() {
  mkdir -p "${PERF_REQUEST_LOG_DIR}"
  # Druid's uid 1000 writes the request log; container uids map elsewhere under rootless Docker.
  chmod 777 "${PERF_REQUEST_LOG_DIR}"
  load_secrets
  build_images
  # The loader empties the extensions volume before downloading, and `up`
  # restarts it, so it runs alone and never beside a running Druid JVM. After a
  # reboot Docker restarts the JVMs (restart: always) on the loaded volume.
  if ! druid_jvms_running; then
    druid_compose build extension_loader
    druid_compose run --rm volumes-init
    druid_compose up -d extension_loader
    druid_compose wait extension_loader
  fi
  # Recreates only the services whose configuration changed, such as an edit
  # to druid.override.yaml; segments stay in the named volumes.
  druid_compose up -d --no-deps "${DRUID_SERVICES[@]}"
  wait_for 'Druid coordinator, broker, middlemanager and historical are up' 60 druid_ready
  broker_sees_datasource || index_druid
  web_compose up -d --wait postgres redis
  web_compose up -d web
  wait_for "web is up at http://127.0.0.1:${PERF_WEB_PORT}" 120 web_answers
  apply_hasura_metadata
}

# Re-index (pass --force to build a new datasource from unchanged files) and
# point the running web at the result.
index() {
  load_secrets
  use_built_image
  index_druid "$@"
  web_compose exec -T web python scripts/druid/update_db_datasource.py
  web_compose restart web
  wait_for "web is up at http://127.0.0.1:${PERF_WEB_PORT}" 120 web_answers
}

# client <repo root> <staged dir>: the production client of that tree (`yarn
# build`, as WP-0e's checks build it on the host's Node 24), staged for
# ui.nginx.conf: web/public/build/min as /build/min/, plus every sourcemap.json
# name (`bundle.css`, `navbar.bundle.js`) at /build/<name>, where the
# non-production templates ask for it.
client() {
  local root="$1" staged="$2"
  ( cd "${root}"
    NODE_OPTIONS=--dns-result-order=ipv4first yarn install --frozen-lockfile --ignore-scripts
    yarn build )
  rm -rf "${staged}"
  mkdir -p "${staged}"
  cp -a "${root}/web/public/build/min" "${staged}/min"
  uv run --no-project python - "${staged}" <<'PY'
import json, os, sys
staged = sys.argv[1]
for name, path in json.load(open(os.path.join(staged, 'min', 'sourcemap.json'))).items():
    if path.startswith('/build/min/') and '/' not in name:
        os.symlink(os.path.join('min', path[len('/build/min/'):]), os.path.join(staged, name))
PY
}

# The staged client is rebuilt only when a client input changed since the
# commit it was built from (client.sha), or with PERF_REBUILD=1: a build
# installs about 840 MB of node_modules into the checkout.
ui() {
  local built="${PERF_SCRATCH}/client.sha"
  load_secrets
  use_built_image
  if [[ -z "${PERF_REBUILD:-}" && -d "${PERF_SCRATCH}/client/min" && -f "${built}" ]] &&
    client_unchanged_since "$(cat "${built}")"; then
    echo "perf stack: the client is unchanged since $(cat "${built}"); serving the staged build"
  else
    rm -f "${built}"
    client "${ROOT}" "${PERF_SCRATCH}/client"
    # A build from uncommitted client edits matches no commit.
    if client_unchanged_since HEAD; then
      git -C "${ROOT}" rev-parse HEAD > "${built}"
    fi
  fi
  web_compose --profile ui up -d ui
  wait_for "the client is served at http://127.0.0.1:${PERF_UI_PORT}" 24 ui_answers
}

# Paths no client build reads. When the reference and this checkout differ
# only here, the reference reuses this checkout's built client.
SERVER_ONLY=(web/server web/python_client scripts docs tests e2e db data config models
  util harmony pipeline druid_setup docker prod .claude .github lint log
  requirements.txt requirements-web.txt requirements-dev.txt requirements-pipeline.txt
  pyproject.toml uv.lock mypy.ini Makefile CLAUDE.md README.md)

client_unchanged_since() {
  local excludes=(. "${SERVER_ONLY[@]/#/:!}")
  git -C "${ROOT}" diff --quiet "$1" -- "${excludes[@]}" &&
    [[ -z "$(git -C "${ROOT}" ls-files --others --exclude-standard -- "${excludes[@]}")" ]]
}

# Start <git ref> beside this checkout, against the same Druid, Postgres and
# Redis, for baseline.py's paired mode: web-reference on PERF_REFERENCE_WEB_PORT
# and ui-reference on PERF_REFERENCE_UI_PORT. The migrations are this
# checkout's (web-init), so a reference must run on the schema they leave.
reference() {
  local ref="${1:?usage: stack.sh reference <git ref>}" sha src="${PERF_REFERENCE_DIR}/src"
  sha="$(git -C "${ROOT}" rev-parse --verify "${ref}^{commit}")"
  load_secrets
  use_built_image
  web_compose --profile reference rm -fs web-reference ui-reference
  rm -rf "${PERF_REFERENCE_DIR}"
  mkdir -p "${src}"
  git -C "${ROOT}" archive --format=tar "${sha}" | tar -x -C "${src}"
  PERF_REFERENCE_IMAGE="$(build_image "${src}")"
  if client_unchanged_since "${sha}"; then
    if [[ ! -d "${PERF_SCRATCH}/client/min" ]]; then
      echo 'perf stack: no built client to share; run stack.sh ui first' >&2
      exit 1
    fi
    echo "perf stack: the client is unchanged since ${sha}; sharing this checkout's build"
    cp -a "${PERF_SCRATCH}/client" "${PERF_REFERENCE_DIR}/client"
  else
    client "${src}" "${PERF_REFERENCE_DIR}/client"
  fi
  echo "${sha}" > "${PERF_REFERENCE_DIR}/sha"
  wait_for 'the reference containers started' 12 start_reference
  wait_for "the reference ${sha} is up at http://127.0.0.1:${PERF_REFERENCE_UI_PORT}" 120 reference_answers
}

# `up` starts the stack again without re-indexing: the segments stay in
# Druid's volumes. Web's Postgres is tmpfs, so web-init runs again.
stop() {
  placeholder_env
  web_compose --profile index --profile ui --profile reference stop
  druid_compose --profile init stop
}

down() {
  placeholder_env
  web_compose --profile index --profile ui --profile reference down --volumes --remove-orphans
  druid_compose --profile init down --volumes --remove-orphans
  rm -rf "${PERF_SCRATCH}"
  rm -f "${SECRETS}"
}

case "${1:-}" in
  dataset) dataset "${@:2}" ;;
  up) up ;;
  index) index "${@:2}" ;;
  ui) ui ;;
  reference) reference "${@:2}" ;;
  stop) stop ;;
  down) down ;;
  env)
    echo "export PERF_CANDIDATE_URL=http://127.0.0.1:${PERF_WEB_PORT}"
    echo "export PERF_CANDIDATE_UI_URL=http://127.0.0.1:${PERF_UI_PORT}"
    echo "export PERF_REFERENCE_URL=http://127.0.0.1:${PERF_REFERENCE_WEB_PORT}"
    echo "export PERF_REFERENCE_UI_URL=http://127.0.0.1:${PERF_REFERENCE_UI_PORT}"
    if [[ -f "${PERF_REFERENCE_DIR}/sha" ]]; then
      echo "export PERF_REFERENCE_SHA=$(cat "${PERF_REFERENCE_DIR}/sha")"
    fi
    echo "export PERF_USERNAME=${PERF_USERNAME}"
    echo "export PERF_CREDENTIALS_FILE=${SECRETS}"
    echo "export PERF_REQUEST_LOG_DIR=${PERF_REQUEST_LOG_DIR}"
    echo "export PERF_BROKER_URL=http://127.0.0.1:${PERF_BROKER_PORT}"
    echo "export PERF_COORDINATOR_URL=http://127.0.0.1:${PERF_COORDINATOR_PORT}"
    ;;
  config)
    placeholder_env
    case "${2:-}" in
      druid) druid_compose --profile init config ;;
      web) web_compose --profile index --profile ui --profile reference config ;;
      *) echo "usage: $0 config druid|web" >&2; exit 2 ;;
    esac
    ;;
  logs)
    placeholder_env
    case "${2:-}" in
      druid) druid_compose logs --tail 200 "${@:3}" ;;
      web) web_compose logs --tail 200 "${@:3}" ;;
      *) echo "usage: $0 logs druid|web [service]" >&2; exit 2 ;;
    esac
    ;;
  *)
    echo "usage: $0 dataset|up|index|ui|reference <ref>|stop|down|env|config druid|web|logs druid|web [service]" >&2
    exit 2
    ;;
esac
