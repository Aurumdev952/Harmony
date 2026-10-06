#!/bin/bash
# Entrypoint of the web image: run the command as the unprivileged app user.
#
# The image runs as uid 1000 (USER in docker/web/Dockerfile_web, `user:` in
# docker-compose.prod.yaml) and never as root. Root-owned data left by images
# before WP-3b is handed over by the one-shot data-owner service
# (docker/web/hand_over_data.sh) before web and worker start.
set -euo pipefail

if (( EUID == 0 )); then
  echo 'run_as_zenysis: refusing to run as root; run as uid 1000 (see docker/web/hand_over_data.sh)' >&2
  exit 1
fi
exec "$@"
