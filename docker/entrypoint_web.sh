#!/bin/bash -eu
set -o pipefail

# A JSON line like the app's (WP-2g), so `docker compose logs web | jq` parses.
# Messages are fixed strings without quotes or backslashes.
log_json() {
  printf '{"timestamp":"%s","level":"INFO","logger":"%s","message":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)" "${0##*/}" "$1"
}

# Script called from docker to upgrade and run the web server in production.

# File that will be created to show that entrypoint initialization has been
# completed. Allows us to skip DB upgrading when the container is reused. When
# `docker restart web` is called, the same container filesystem will be used and
# this flag will be set.
INIT_COMPLETE='/tmp/initialization_completed'

pushd /zenysis &>/dev/null

if ! [ -f "${INIT_COMPLETE}" ] ; then
  log_json 'Initializing server'
  ./initialize_new_container.sh

  log_json 'Initialization complete'
  touch "${INIT_COMPLETE}"
fi

log_json 'Running server...'
./run_web_gunicorn.sh

popd &>/dev/null
