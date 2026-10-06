#!/bin/bash
# Proves the unit suite can fail: applies one mutant at a time to a scratch
# copy of web/client and reports the suite result for each. Every mutant line
# must show failed tests. The checkout itself is never modified.
#
#   tests/frontend/mutants.sh
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT

mkdir -p "${SCRATCH}/web/public/js/vendor" "${SCRATCH}/tests"
cp -r "${ROOT}/web/client" "${SCRATCH}/web/client"
cp "${ROOT}/web/public/js/vendor/jquery-3.6.0.js" "${SCRATCH}/web/public/js/vendor/"
cp -r "${ROOT}/tests/frontend" "${ROOT}/tests/golden" "${SCRATCH}/tests/"
cp "${ROOT}/vitest.config.ts" "${ROOT}/package.json" "${SCRATCH}/"
ln -s "${ROOT}/node_modules" "${SCRATCH}/node_modules"

run_suite() {
  (cd "${SCRATCH}" && npx vitest run 2>&1 | grep -E '^ +Tests ' | tr -s ' ')
}

survivors=0
mutate() {
  local name="$1" file="${SCRATCH}/$2"
  cp "${file}" "${file}.orig"
  FROM="$3" TO="$4" perl -0pi -e 's/\Q$ENV{FROM}\E/$ENV{TO}/' "${file}"
  if cmp -s "${file}" "${file}.orig"; then
    echo "${name}: pattern not found, update this script"
    survivors=$((survivors + 1))
  else
    local result
    result="$(run_suite)"
    echo "${name}:${result}"
    [[ "${result}" == *failed* ]] || survivors=$((survivors + 1))
  fi
  mv "${file}.orig" "${file}"
}

echo "baseline:$(run_suite)"
mutate apiservice-v2-prefix web/client/services/APIService.js \
  "V2: '/api2'," "V2: '/api',"
mutate ethiopian-pagume-merge web/client/util/dateUtil.js \
  'mergePagumeIntoMeskerem && month === 13' 'mergePagumeIntoMeskerem && month === 12'
mutate apitoken-sends-secret web/client/services/models/APIToken.js \
  $'      id,\n      isRevoked,' $'      id,\n      token: this.modelValues().token,\n      isRevoked,'
mutate uri-to-id-keeps-slash web/client/services/wip/util.js \
  "\${endpoint}/\`, '')" "\${endpoint}\`, '')"
mutate serialize-array-drops-first web/client/lib/Zen/util/serializationUtil.js \
  'return models.map(m => m.serialize());' 'return models.slice(1).map(m => m.serialize());'

echo "surviving mutants: ${survivors}"
exit $((survivors > 0))
