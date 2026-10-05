#!/usr/bin/env bash
# Runs tests/worker/renderer inside a renderer image, with no network and the
# renderer service's hardening from docker-compose.yaml, so the browser tests
# (egress fence, sandbox, maps) run against the Chromium that ships.
#
# Usage: docker/renderer/test_in_image.sh <renderer image> [pytest args...]
set -euo pipefail

image=${1:?usage: $0 <renderer image> [pytest args...]}
shift
repo=$(cd "$(dirname "$0")/../.." && pwd)
iidfile=$(mktemp)
log=$(mktemp)
trap 'rm -f "$iidfile" "$log"' EXIT

docker build \
    -f "$repo/docker/renderer/Dockerfile.test" \
    --build-arg "RENDERER_IMAGE=$image" \
    --iidfile "$iidfile" \
    "$repo"

docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp \
    --tmpfs /home/pwuser \
    --shm-size 1g \
    --init \
    --cap-drop ALL \
    --cap-add SYS_CHROOT \
    --security-opt no-new-privileges:true \
    --security-opt "seccomp=$repo/docker/renderer/seccomp_profile.json" \
    --memory 2g \
    --pids-limit 512 \
    -v "$repo/tests/worker/renderer:/src/tests/worker/renderer:ro" \
    -v "$repo/pyproject.toml:/src/pyproject.toml:ro" \
    "$(cat "$iidfile")" \
    /src/tests/worker/renderer "$@" 2>&1 | tee "$log"

# The browser tests skip wherever Playwright is missing. Here it is not, so a
# skip means they did not run.
if grep -Eq '\b[0-9]+ skipped\b' "$log"; then
    echo 'renderer tests were skipped inside the image' >&2
    exit 1
fi
