#!/bin/bash
# driver.sh <tree> <runs> <rows...>: time harmony_demo's three per-row process steps
# (00_self_serve/10_process, 00_yellow_fever/10_process, 90_shared fill) in the old
# pipeline image (PyPy 3.8) and the 3.13 image with <tree>'s pipeline code mounted,
# interleaved run by run because the host is loaded. Prints one line per run with
# wall time and peak RSS per step, then the md5 of every output (digest.sh).
# Scratch goes to $SCRATCH (default /tmp/wp3b-pipe); clean.sh removes it.
TREE="$1"; RUNS="$2"; shift 2
S=$(cd "$(dirname "$0")" && pwd -P)
P=${SCRATCH:-/tmp/wp3b-pipe}
BASE=${BASE_IMAGE:-local/wp4a-infra/harmony-pipeline:test}
BRANCH=${BRANCH_IMAGE:-local/wp3b-infra3d/harmony-etl-pipeline:d2}
# The tree's pipeline code, read-only: neither image carries bytecode for the app
# code and uid 1000 cannot write it, so both compile it on every run.
bash "$S/clean.sh" "$P" branch_src; mkdir -p "$P/branch_src/data"
cp -r "$TREE/data/pipeline" "$P/branch_src/data/pipeline"
cp -r "$TREE/util/pipeline" "$P/branch_src/util_pipeline"
cp -r "$TREE/pipeline" "$P/branch_src/pipeline"
find "$P/branch_src" -name __pycache__ -prune -exec rm -rf {} +
BRANCH_MOUNTS=(-v "$P/branch_src/data/pipeline:/zenysis/data/pipeline:ro"
  -v "$P/branch_src/util_pipeline:/zenysis/util/pipeline:ro"
  -v "$P/branch_src/pipeline:/zenysis/pipeline:ro")

for rows in "$@"; do
  if [ ! -d "$P/inputs/$rows" ]; then
    (cd "$TREE" && uvx --from uv==0.12.23 uv run python "$S/make_inputs.py" "$TREE" "$P/inputs/$rows" "$rows") || exit 1
  fi
  for run in $(seq 1 "$RUNS"); do
    for tag in base branch; do
      W="$P/runs/$rows-$tag-$run"
      bash "$S/clean.sh" "$P" "runs/$rows-$tag-$run"
      mkdir -p "$W" && cp -r "$P/inputs/$rows/feed" "$W/feed" && chmod -R a+rwX "$W"
      if [ "$tag" = base ]; then img=$BASE; mounts=(); else img=$BRANCH; mounts=("${BRANCH_MOUNTS[@]}"); fi
      res=$(docker run --rm --user 1000:1000 --network none -v "$W":/work -v "$S":/probe:ro \
        "${mounts[@]}" --entrypoint bash "$img" /probe/in_container.sh 2>&1 | tr '\n' ' ')
      echo "rows=$rows image=$tag run=$run load=$(cut -d' ' -f1 /proc/loadavg) $res"
      echo "  outputs $(bash "$S/digest.sh" "$W")"
    done
  done
done
