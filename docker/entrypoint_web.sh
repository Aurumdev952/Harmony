#!/bin/bash -eu
set -o pipefail

# JSON log lines (WP-2g); the image copies docker/web/scripts/log_json.sh here.
# shellcheck source=docker/web/scripts/log_json.sh
source /zenysis/log_json.sh

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
