#!/bin/bash -eu
set -o pipefail

# Relay compiles against the schema the proxy exposes to signed-in users, so
# introspect as role `user`, not as admin. The admin secret stays in the
# environment (HASURA_ADMIN_SECRET) and never reaches a command line.

ZEN_SRC_ROOT=$(git rev-parse --show-toplevel)

pushd "${ZEN_SRC_ROOT}" &> /dev/null

DESTINATION='graphql/schema.graphql'
: "${HASURA_ADMIN_SECRET:?HASURA_ADMIN_SECRET must be set}"

echo "Updating schema in <src-root>/${DESTINATION} with the hasura schema for role user"
SCHEMA=$(scripts/db/hasura/check_role_permissions.py \
  --hasura_host "${HASURA_HOST:-http://localhost:8088}" \
  --print-schema user)
printf '%s\n' "${SCHEMA}" > "${DESTINATION}"

popd &> /dev/null
