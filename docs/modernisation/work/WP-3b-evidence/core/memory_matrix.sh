#!/bin/bash
# Old path: base tree (ijson-bigint yajl2_c, the backend the 3.8 image used) on 3.9.
# New path: this branch (msgspec + bounded read) on 3.13.
WT=/home/aurum/aurum/work/zenysis/Harmony/.claude/worktrees/agent-aad20f626d9a84785
GOLDEN=$WT/tests/golden/cases/dq_data_quality/druid_response.json
BIG=/tmp/core3b/body_200mb.json.gz
run() {
  local label=$1; shift
  /usr/bin/time -v "$@" 2>/tmp/core3b/time.err | sed "s/^/$label\t/"
  grep -E "Maximum resident set size" /tmp/core3b/time.err | sed "s/^\s*/$label\t  process /"
}
for body in "$GOLDEN" "$BIG"; do
  for mode in stream retain; do
    run old uv run --project /tmp/core3b/base python /tmp/core3b/memory_bench.py /tmp/core3b/base "$body" "$mode"
    run new uvx --from uv==0.12.23 uv run --project "$WT" python /tmp/core3b/memory_bench.py "$WT" "$body" "$mode"
  done
done
