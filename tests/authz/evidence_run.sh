#!/bin/bash
# Fresh-stack evidence run for WP-2b: recreate the stack, run the whole suite
# with the stack env set (pure and live-stack layers), run the live-stack layer
# twice more to show the provisioning is idempotent, then print what the runs
# left behind in the stack's database. Output goes to $1.
#
# AUTHZ_PROJECT and AUTHZ_WEB_PORT pick the stack, as for stack.sh. A failed
# stack step stops the run; a failed test run is reported and the run goes on.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
OUT="${1:?usage: evidence_run.sh <output file>}"
PROJECT="${AUTHZ_PROJECT:-harmony-wp2b-authz}"
LEFTOVERS="select 'users=' || (select count(*) from \"user\" where username like '%@authz.invalid')
  || ' groups=' || (select count(*) from security_group)
  || ' authz_roles=' || (select count(*) from role where name like 'authz%')
  || ' saved_queries=' || (select count(*) from user_query_session)
  || ' api_tokens=' || (select count(*) from api_token)"

run_suite() {
  local status=0
  "${HERE}/run.sh" "$@" > "${OUT}.log" 2>&1 || status=$?
  grep -E '^FAILED|^ERROR|passed|failed' "${OUT}.log" || true
  echo "exit ${status}"
  rm -f "${OUT}.log"
}

exec > "${OUT}" 2>&1
echo "== stack down/up (${PROJECT})"
"${HERE}/stack.sh" down
"${HERE}/stack.sh" up
eval "$("${HERE}/stack.sh" env)"
echo "== whole suite, stack env set (pure and live-stack layers)"
run_suite
echo "== live-stack layer, run 2"
run_suite -m authz_http
echo "== live-stack layer, run 3"
run_suite -m authz_http
echo "== left in the stack database"
docker exec "${PROJECT}-postgres-1" \
  psql -U postgres -d harmony_demo-local -tAc "${LEFTOVERS}"
