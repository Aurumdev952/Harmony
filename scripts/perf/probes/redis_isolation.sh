#!/bin/bash
# Checks that the candidate and the reference web use different Redis servers
# (decision 0011): a key written through web-reference's REDIS_HOST must be
# absent from web's. Needs `stack.sh up` and `stack.sh reference` running.
#
#   scripts/perf/probes/redis_isolation.sh
set -euo pipefail

project="${PERF_PROJECT:-harmony-wp1a-perf}-web"
probe='import os, sys, redis
r = redis.Redis(host=os.environ["REDIS_HOST"], password=os.environ["REDIS_PASSWORD"])
if sys.argv[1] == "set":
    r.set("perf-redis-isolation", "1")
print(os.environ["REDIS_HOST"], "has the key:", bool(r.exists("perf-redis-isolation")))
if sys.argv[1] == "del":
    r.delete("perf-redis-isolation")'

run() {
  docker compose -p "${project}" exec -T "$1" python -W ignore -c "${probe}" "$2"
}

run web-reference set
seen="$(run web get)"
echo "${seen}"
run web-reference del
[[ "${seen}" == *"has the key: False" ]]
