#!/bin/bash
# The performance-baseline stack: Druid 0.23 from druid_setup/single, loaded with
# the synthetic harmony_demo dataset, and the web app pointed at it.
#
#   scripts/perf/stack.sh dataset   # generate the CSV, run process_csv and fill_dimension_data
#   scripts/perf/stack.sh up        # build web, start Druid, index the dataset if Druid has none, start web
#   scripts/perf/stack.sh index [--force]   # re-index, register the datasource with web, restart web
#   scripts/perf/stack.sh down      # stop everything, delete volumes, scratch and secrets
#   scripts/perf/stack.sh env       # what baseline.py and dashboards.mjs read
#   scripts/perf/stack.sh logs druid|web [service]
#   scripts/perf/stack.sh config druid|web   # the merged Compose file
#
# Concurrent stacks need their own PERF_PROJECT and ports:
#   PERF_PROJECT          default harmony-wp1a-perf (Compose projects <name>-druid, <name>-web)
#   PERF_WEB_PORT         default 58700
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
export PERF_COORDINATOR_PORT="${PERF_COORDINATOR_PORT:-58981}"
export PERF_BROKER_PORT="${PERF_BROKER_PORT:-58982}"
export PERF_ROUTER_PORT="${PERF_ROUTER_PORT:-58988}"
export PERF_SCRATCH="${PERF_SCRATCH:-${TMPDIR:-/tmp}/${PERF_PROJECT}}"
export PERF_REQUEST_LOG_DIR="${PERF_SCRATCH}/broker-requests"
export PERF_USERNAME="${PERF_USERNAME:-perf-admin@harmony.invalid}"
export PERF_REPO_ROOT="${ROOT}"
export PERF_STACK_DIR="${HERE}/stack"
# Read by druid_setup/single before WP-0b (image tags) and after it (bind address).
export DRUID_VERSION=0.23.0 ZOOKEEPER_VERSION=3.8 DRUID_BIND_ADDRESS=127.0.0.1

SECRETS_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/harmony-perf"
SECRETS="${SECRETS_DIR}/${PERF_PROJECT}.env"
SECRET_NAMES=(PERF_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD HASURA_ADMIN_SECRET DEFAULT_SECRET_KEY JWT_SECRET_KEY DRUID_POSTGRES_PASSWORD)

# The digest WP-2c's contract stack builds docker/web/Dockerfile_web-server from.
PYTHON_38="python:3.8@sha256:d411270700143fa2683cc8264d9fa5d3279fd3b6afff62ae81ea2f9d070e390c"

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

image_tag() {
  cat "${ROOT}/requirements.txt" "${ROOT}/requirements-web.txt" \
    "${ROOT}/docker/web/Dockerfile_web-server" "${HERE}/stack/Dockerfile" | sha256sum | cut -c1-12
}

build_images() {
  local tag
  tag="$(image_tag)"
  docker build --platform linux/amd64 \
    --build-context "python:3.8=docker-image://${PYTHON_38}" \
    -f "${ROOT}/docker/web/Dockerfile_web-server" \
    -t "harmony-perf-web-server:${tag}" "${ROOT}"
  docker build --platform linux/amd64 \
    --build-arg "BASE_IMAGE=harmony-perf-web-server:${tag}" \
    -t "harmony-perf-web:${tag}" "${HERE}/stack"
  export PERF_WEB_IMAGE="harmony-perf-web:${tag}"
}

use_built_image() {
  PERF_WEB_IMAGE="harmony-perf-web:$(image_tag)"
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

down() {
  placeholder_env
  web_compose --profile index down --volumes --remove-orphans
  druid_compose --profile init down --volumes --remove-orphans
  rm -rf "${PERF_SCRATCH}"
  rm -f "${SECRETS}"
}

case "${1:-}" in
  dataset) dataset "${@:2}" ;;
  up) up ;;
  index) index "${@:2}" ;;
  down) down ;;
  env)
    echo "export PERF_BASE_URL=http://127.0.0.1:${PERF_WEB_PORT}"
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
      web) web_compose --profile index config ;;
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
    echo "usage: $0 dataset|up|index|down|env|config druid|web|logs druid|web [service]" >&2
    exit 2
    ;;
esac
