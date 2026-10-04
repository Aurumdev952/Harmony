#!/bin/bash -eu
set -o pipefail

ZEN_SRC_ROOT=$(git rev-parse --show-toplevel)

pushd "${ZEN_SRC_ROOT}" &> /dev/null

DESTINATION='graphql/schema.graphql'

echo "Updating schema in <src-root>/${DESTINATION} with latest version in hasura"
node_modules/.bin/gq 'http://localhost:8088/v1beta1/relay' \
  -H "X-Hasura-Admin-Secret: ${HASURA_ADMIN_SECRET:?HASURA_ADMIN_SECRET must be set}" \
  --introspect > "${DESTINATION}"

popd &> /dev/null
