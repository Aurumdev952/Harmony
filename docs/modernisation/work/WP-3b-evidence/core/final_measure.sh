#!/bin/bash
# Wait for a quiet host, then take every PERF-7 timing on the final code.
WT=/home/aurum/aurum/work/zenysis/Harmony/.claude/worktrees/agent-aad20f626d9a84785
echo "start load $(cut -d' ' -f1-3 /proc/loadavg)"
cd "$WT"
echo "== parse bench (200,000 rows; best of 5; peak RSS growth MB)"
for shape in array dict; do
  uv run --project /tmp/core3b/base python docs/modernisation/work/WP-3b-evidence/core/parse_bench.py run ijson_yajl2_c $shape 2>/dev/null
  for v in client ijson_python json orjson msgspec; do
    uvx --from uv==0.12.23 uv run --locked --with ijson-bigint==3.2.0.post1 --with orjson==3.12.0 --with msgspec==0.21.1 \
      python docs/modernisation/work/WP-3b-evidence/core/parse_bench.py run $v $shape 2>/dev/null
  done
done
echo "== memory matrix"
bash /tmp/core3b/memory_matrix.sh 2>&1 | grep -v -i warning
echo "== end to end"
for n in 200000 600000; do
  uv run --project /tmp/core3b/base python /tmp/core3b/e2e_bench.py /tmp/core3b/base $n 2>/dev/null | tail -1
  FORCE_IJSON=python uvx --from uv==0.12.23 uv run --project "$WT" --with ijson-bigint==3.2.0.post1 python /tmp/core3b/e2e_bench.py /tmp/core3b/prefix $n 2>/dev/null | tail -1
  uvx --from uv==0.12.23 uv run --project "$WT" python /tmp/core3b/e2e_bench.py "$WT" $n 2>/dev/null | tail -1
done
echo "end load $(cut -d' ' -f1-3 /proc/loadavg)"
