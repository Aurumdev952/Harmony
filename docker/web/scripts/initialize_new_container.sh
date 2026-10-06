#!/bin/bash -eu
set -o pipefail

# JSON log lines (WP-2g).
# shellcheck source=docker/web/scripts/log_json.sh
source "$(dirname "${BASH_SOURCE[0]}")/log_json.sh"

# Run specific initialization steps that are needed when a new docker web
# container is being run for the first time.
DEFAULT_HASURA_HOST='http://hasura:8080'

# Copy static assets to a directory that nginx can access.
log_json 'Copying static files...'
mkdir -p /data/output/zenysis_static
rm -rf /data/output/zenysis_static/*
cp -r /zenysis/web/public/{build,images,js} /data/output/zenysis_static

log_json 'Running db upgrade...'
FLASK_APP='web.server.app' ZEN_OFFLINE=1 flask db upgrade

# Apply hasura metadata
log_json 'Applying hasura metadata'
scripts/db/hasura/apply_metadata_snapshot.py --hasura_host "${HASURA_HOST:-$DEFAULT_HASURA_HOST}"

# NOTE: populate query models if we have this flag enabled
# This is dangerous and can potentially truncate production
# data catalog models. This shouldn't be enabled for staging/production
# instances.
if [ -n "${POPULATE_QUERY_MODELS_FROM_CONFIG:-}" ] ; then
  log_json 'Populating query models from config'
  scripts/data_catalog/populate_query_models_from_config.py
fi
