#!/bin/bash -eu
set -o pipefail

# A JSON line like the app's (WP-2g), so `docker compose logs web | jq` parses.
# Messages are fixed strings without quotes or backslashes.
log_json() {
  printf '{"timestamp":"%s","level":"INFO","logger":"%s","message":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%S.000+00:00)" "${0##*/}" "$1"
}

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
