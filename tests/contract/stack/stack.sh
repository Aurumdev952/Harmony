#!/bin/bash
# Bring the contract stack up or down.
#
#   tests/contract/stack/stack.sh up     # build, start, seed, wait for web
#   tests/contract/stack/stack.sh down   # stop, delete containers, tmpfs data and secrets
#   tests/contract/stack/stack.sh logs [service]
#   tests/contract/stack/stack.sh env    # print what the recorder and replay need
#   tests/contract/stack/stack.sh seed thumbnail <dashboard resource id>
#                                        # the runner calls this for a case's `seed`
#
# Concurrent stacks (one per CI job or worktree) need their own
#   CONTRACT_PROJECT   compose project name, default harmony-wp2c-contract
#   CONTRACT_WEB_PORT  loopback port for web, default 58650
# e.g. CONTRACT_PROJECT=contract-$CI_JOB_ID CONTRACT_WEB_PORT=$((40000 + RANDOM % 20000)).
#
# Every secret (admin password, Postgres, Redis, Hasura admin, session and JWT
# keys) is generated per stack into a mode-600 file outside the repository, so
# none lands in fixtures, logs or git (SPEC INV-6).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "${HERE}/../../.." && pwd -P)"
export CONTRACT_PROJECT="${CONTRACT_PROJECT:-harmony-wp2c-contract}"
export CONTRACT_WEB_PORT="${CONTRACT_WEB_PORT:-58650}"
export CONTRACT_USERNAME="${CONTRACT_USERNAME:-contract-admin@harmony.invalid}"

SECRETS_DIR="${XDG_RUNTIME_DIR:-${HOME}/.local/state/harmony-contract}"
SECRETS="${SECRETS_DIR}/${CONTRACT_PROJECT}.env"
SECRET_NAMES=(CONTRACT_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD HASURA_ADMIN_SECRET DEFAULT_SECRET_KEY JWT_SECRET_KEY)

compose_files() {
  local files=(-f "${HERE}/compose.yaml")
  # Match the secrets Redis and Hasura demand to what the checked-out code sends.
  if [[ -f "${ROOT}/web/server/configuration/redis_connection.py" ]]; then
    files+=(-f "${HERE}/compose.redis-auth.yaml")
  fi
  if grep -q HASURA_ADMIN_SECRET "${ROOT}/web/server/configuration/flask.py"; then
    files+=(-f "${HERE}/compose.hasura-secret.yaml")
  fi
  printf '%s\n' "${files[@]}"
}

compose() {
  local files
  mapfile -t files < <(compose_files)
  docker compose -p "${CONTRACT_PROJECT}" "${files[@]}" "$@"
}

new_secret() {
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

create_secrets() {
  mkdir -p -m 700 "${SECRETS_DIR}"
  ( umask 077
    for name in "${SECRET_NAMES[@]}"; do
      printf '%s=%s\n' "${name}" "$(new_secret)"
    done > "${SECRETS}" )
}

# Read only the expected NAME=value lines; never source the file as shell.
load_secrets() {
  [[ -f "${SECRETS}" ]] || create_secrets
  local owner mode
  read -r owner mode < <(stat -c '%u %a' "${SECRETS}")
  if [[ "${owner}" != "$(id -u)" || "${mode}" != "600" ]]; then
    echo "contract stack: refusing ${SECRETS}: it must be owned by you with mode 600" >&2
    exit 1
  fi
  local name value
  for name in "${SECRET_NAMES[@]}"; do
    value="$(grep -m1 "^${name}=[0-9a-f]\{64\}$" "${SECRETS}" | cut -d= -f2 || true)"
    if [[ -z "${value}" ]]; then
      echo "contract stack: ${SECRETS} has no valid ${name}; run stack.sh down" >&2
      exit 1
    fi
    export "${name}=${value}"
  done
}

# Tag by what the image is built from, so stacks from different checkouts never
# share an image silently; the build itself always runs (the layer cache makes
# an unchanged rebuild quick).
build_images() {
  local hash
  hash="$(cat "${ROOT}/requirements.txt" "${ROOT}/requirements-web.txt" \
    "${ROOT}/docker/web/Dockerfile_web-server" | sha256sum | cut -c1-12)"
  docker build --platform linux/amd64 \
    -f "${ROOT}/docker/web/Dockerfile_web-server" \
    -t "harmony-contract-web-server:${hash}" "${ROOT}"
  export CONTRACT_WEB_IMAGE="harmony-contract-web-server:${hash}"
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
  echo 'contract stack: web did not become ready; see `stack.sh logs web`' >&2
  return 1
}

apply_hasura_metadata() {
  for _ in $(seq 1 60); do
    if compose exec -T web python -c "import requests; requests.get('http://hasura:8080/healthz', timeout=2).raise_for_status()" 2>/dev/null; then
      compose exec -T web python scripts/db/hasura/apply_metadata_snapshot.py --hasura_host http://hasura:8080
      return 0
    fi
    sleep 2
  done
  echo 'contract stack: hasura did not become ready; GraphQL cases will fail' >&2
  return 1
}

# Compose interpolates every variable even for down and logs.
placeholder_env() {
  export CONTRACT_WEB_IMAGE="${CONTRACT_WEB_IMAGE:-unused}"
  local name
  for name in "${SECRET_NAMES[@]}"; do
    export "${name}=${!name:-unused}"
  done
}

case "${1:-}" in
  up)
    load_secrets
    build_images
    compose up -d --wait postgres redis druid-stub mailpit
    compose up -d forward
    wait_for_web
    apply_hasura_metadata
    ;;
  down)
    placeholder_env
    compose down --volumes --remove-orphans
    rm -f "${SECRETS}"
    ;;
  logs)
    placeholder_env
    compose logs --tail 200 "${@:2}"
    ;;
  seed)
    placeholder_env
    case "${2:-}" in
      thumbnail)
        compose exec -T web python tests/contract/stack/seed_cache.py "${3:?dashboard resource id}"
        ;;
      *)
        echo "usage: $0 seed thumbnail <dashboard resource id>" >&2
        exit 2
        ;;
    esac
    ;;
  env)
    echo "export CONTRACT_PROJECT=${CONTRACT_PROJECT}"
    echo "export CONTRACT_BASE_URL=http://127.0.0.1:${CONTRACT_WEB_PORT}"
    echo "export CONTRACT_USERNAME=${CONTRACT_USERNAME}"
    echo "export CONTRACT_CREDENTIALS_FILE=${SECRETS}"
    ;;
  *)
    echo "usage: $0 up|down|logs [service]|env|seed thumbnail <id>" >&2
    exit 2
    ;;
esac
