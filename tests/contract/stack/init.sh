#!/bin/bash
# Prepares the disposable contract database: schema migrations, then the
# seeded admin user the recorder logs in as. Runs inside the web-init service.
set -euo pipefail
cd /src
: "${CONTRACT_PASSWORD:?set by tests/contract/stack/stack.sh up}"

echo 'contract-init: flask db upgrade'
FLASK_APP='web.server.app' flask db upgrade

echo 'contract-init: create admin user'
python scripts/create_user.py \
  --username "${CONTRACT_USERNAME}" \
  --password "${CONTRACT_PASSWORD}" \
  --first_name Contract \
  --last_name Admin \
  --site_admin \
  --overwrite

python tests/contract/stack/seed_catalog.py

echo 'contract-init: done'
