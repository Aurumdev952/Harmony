#!/bin/bash
# Runs a private instance of the WP-2c contract stack (tests/contract/stack) for
# the live layer of the authorisation suite, under its own project name and
# port so it never shares a database with the contract recorder.
#
#   tests/authz/stack.sh up      # build, start, migrate, seed the admin, wait for web
#   tests/authz/stack.sh env     # print the env tests/authz/http needs
#   tests/authz/stack.sh logs [service]
#   tests/authz/stack.sh down    # stop and delete containers, tmpfs data and secrets
#
# The contract stack generates every secret per stack into a mode-600 file
# outside the repository (SPEC INV-6).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
CONTRACT_STACK="${HERE}/../contract/stack/stack.sh"
export CONTRACT_PROJECT="${AUTHZ_PROJECT:-harmony-wp2b-authz}"
export CONTRACT_WEB_PORT="${AUTHZ_WEB_PORT:-58660}"
export CONTRACT_USERNAME="${AUTHZ_ADMIN_USERNAME:-authz-admin@harmony.invalid}"

if [[ ! -x "${CONTRACT_STACK}" ]]; then
  echo "authz stack: ${CONTRACT_STACK} is missing; it arrives with WP-2c" >&2
  exit 2
fi

case "${1:-}" in
  up|down|logs)
    exec "${CONTRACT_STACK}" "$@"
    ;;
  env)
    eval "$("${CONTRACT_STACK}" env)"
    echo "export AUTHZ_BASE_URL=${CONTRACT_BASE_URL}"
    echo "export AUTHZ_ADMIN_USERNAME=${CONTRACT_USERNAME}"
    echo "export AUTHZ_CREDENTIALS_FILE=${CONTRACT_CREDENTIALS_FILE}"
    echo "export AUTHZ_PROJECT=${CONTRACT_PROJECT}"
    ;;
  *)
    echo "usage: $0 up|down|logs [service]|env" >&2
    exit 2
    ;;
esac
