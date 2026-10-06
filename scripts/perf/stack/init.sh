#!/bin/bash
# Prepares the disposable perf database: schema migrations and the site
# administrator baseline.py and the dashboard script log in as (the steps of
# WP-2c's tests/contract/stack/init.sh), then registers the newest Druid
# datasource as the pipeline's validate step does. Runs inside web-init.
set -euo pipefail
cd /src
: "${PERF_PASSWORD:?set by scripts/perf/stack.sh up}"

echo 'perf-init: flask db upgrade'
FLASK_APP='web.server.app' flask db upgrade

echo 'perf-init: create admin user'
python scripts/create_user.py \
  --username "${PERF_USERNAME}" \
  --password "${PERF_PASSWORD}" \
  --first_name Perf \
  --last_name Admin \
  --site_admin \
  --overwrite

echo 'perf-init: register the newest Druid datasource'
python scripts/druid/update_db_datasource.py

echo 'perf-init: done'
