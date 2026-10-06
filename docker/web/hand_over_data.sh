#!/bin/bash
# One-shot, as root: hand the paths web and worker write to uid 1000.
#
# Images before WP-3b ran as root, so on an existing host the bind-mounted static
# files, logs and uploads are root-owned. The data-owner service in
# docker-compose.prod.yaml runs this before web and worker start, with only the
# CHOWN and DAC_READ_SEARCH capabilities and no network, then exits. After the
# first run it finds nothing to change.
#
# uid 1000 may have planted symlinks in these trees. Nothing here follows one:
# find does not follow symlinks (-P), -execdir runs chown from each entry's own
# directory, and chown -h changes a symlink itself, never its target.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

APP_UID=1000
APP_GID=1000

# hand_over <dir> [find options and tests]
hand_over() {
  find -P "$1" -xdev "${@:2}" ! -user "$APP_UID" -execdir chown -h "$APP_UID:$APP_GID" {} +
}

if [[ -d /data/output && ! -L /data/output ]]; then
  # The directory itself and its log files, not other services' subdirectories
  # (hasura writes /data/output/logs).
  hand_over /data/output -maxdepth 0
  hand_over /data/output -mindepth 1 -maxdepth 1 -name '*.log*'
  if [[ -d /data/output/zenysis_static && ! -L /data/output/zenysis_static ]]; then
    hand_over /data/output/zenysis_static
  fi
fi
if [[ -d /zenysis/uploads && ! -L /zenysis/uploads ]]; then
  hand_over /zenysis/uploads
fi
