#!/bin/bash
# Fresh-stack evidence run for WP-2b: recreate the stack, run the pure and the
# live-stack layers, then run the live-stack layer again to show the
# provisioning is idempotent. Output goes to $1.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
OUT="${1:?usage: evidence_run.sh <output file>}"

{
  echo "== stack down/up"
  "${HERE}/stack.sh" down
  "${HERE}/stack.sh" up
  eval "$("${HERE}/stack.sh" env)"
  echo "== pure layer"
  "${HERE}/run.sh" 2>&1 | grep -v WARNING | tail -3
  echo "== live-stack layer, run 1"
  "${HERE}/run.sh" -m authz_http 2>&1 | grep -v WARNING | grep -E '^FAILED|passed|failed'
  echo "== live-stack layer, run 2"
  "${HERE}/run.sh" -m authz_http 2>&1 | grep -v WARNING | grep -E '^FAILED|passed|failed'
} > "${OUT}" 2>&1
