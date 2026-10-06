#!/bin/bash
# clean.sh <scratch> <relative path>: delete <scratch>/<path>. Files a container wrote
# as uid 1000 are not deletable by the host user here (uid remapping), so the same
# image and uid delete them first.
P="$1"; rel="$2"
case "$rel" in "" | /* | *..*) echo "refusing: $rel"; exit 1 ;; esac
[ -e "$P/$rel" ] || exit 0
docker run --rm --user 1000:1000 --network none -v "$P":/p --entrypoint rm \
  "${BRANCH_IMAGE:-local/wp3b-infra3d/harmony-etl-pipeline:d2}" -rf "/p/$rel" 2>/dev/null
rm -rf "${P:?}/$rel"
