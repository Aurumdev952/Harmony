#!/bin/bash -eu
set -o pipefail

# if docker command doesn't exist, assume we're running containerized and quit
if ! command -v docker &> /dev/null
then
  echo "Docker command does not exist - assuming hasura is running..."
  exit 0
fi

DB_NAME="$1"
CONTAINER_NAME='hasura'
IMAGE_NAME='hasura/graphql-engine:v2.45.8.cli-migrations-v2@sha256:c23e41af28e4c8e27bf6b6e82a5ecdd5b3ba3bb373833f92f5136e25b0ad45c6'
ZEN_SRC_ROOT=$(git rev-parse --show-toplevel)
HASURA_METADATA_DIR="${ZEN_SRC_ROOT}/graphql/hasura/metadata/versions"
HASURA_CONTAINER_SCRIPTS_DIR="${ZEN_SRC_ROOT}/scripts/db/hasura/dev/container"

export HASURA_GRAPHQL_ADMIN_SECRET="${HASURA_ADMIN_SECRET:?HASURA_ADMIN_SECRET must be set to start hasura}"

RUNNING_IMAGE=$(docker inspect -f '{{.Config.Image}}' "${CONTAINER_NAME}" 2> /dev/null) || true
RUNNING_SECRET=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${CONTAINER_NAME}" 2> /dev/null \
  | sed -n 's/^HASURA_GRAPHQL_ADMIN_SECRET=//p') || true
IS_RUNNING=$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2> /dev/null) || true

if [[ "${RUNNING_IMAGE}" != "${IMAGE_NAME}" \
  || "${RUNNING_SECRET}" != "${HASURA_GRAPHQL_ADMIN_SECRET}" \
  || "${IS_RUNNING}" != 'true' ]] ; then
  echo 'Removing previous container (if it exists)'
  docker stop "${CONTAINER_NAME}" &> /dev/null || true
  docker rm "${CONTAINER_NAME}" &> /dev/null || true

  # Run the hasura container in background mode.
  # NOTE: Specifying the `sh` script so that the container runs
  # indefinitely and we can manually change what options are passed in without
  # needing to restart the container.
  echo 'Starting Hasura'
  docker run \
      -d \
      -it \
      --name "${CONTAINER_NAME}" \
      -e HASURA_GRAPHQL_ADMIN_SECRET \
      -v "${HASURA_METADATA_DIR}:/hasura-metadata" \
      -v "${HASURA_CONTAINER_SCRIPTS_DIR}:/zenysis:ro" \
      -p '127.0.0.1:8088:8080' \
      --entrypoint 'sh' \
    "${IMAGE_NAME}"
fi

docker exec -d -it "${CONTAINER_NAME}" /zenysis/switch_db.sh "${DB_NAME}"
