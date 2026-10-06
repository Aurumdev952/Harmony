#!/usr/bin/env bash
# Run harmony_demo's Zeus step process/run/00_yellow_fever/10_process inside a pipeline
# image, as the entrypoint does (venv activated, then the step's SetupEnvForPyPy), on
# the yellow_fever fixture repeated to <rows> rows. Prints the interpreter the step's
# Python ran on, the output sizes and the wall-clock time.
# Usage: zeus_step.sh <image> <rows>
IMG="$1"; ROWS="$2"
TREE=$(cd "$(dirname "$0")/../../../../.." && pwd -P)
FIXTURE="$TREE/tests/pipeline/fixtures/process_csv/yellow_fever/input.csv"
W=$(mktemp -d)
chmod 777 "$W"
mkdir -m 777 "$W/feed" "$W/tmp"
{ head -1 "$FIXTURE"; tail -n +2 "$FIXTURE" | awk -v n="$ROWS" '{rows[NR]=$0} END {for (i = 0; i < n; i++) print rows[i % NR + 1]}'; } > "$W/feed/yellow_fever_cases.csv"
chmod 644 "$W/feed/yellow_fever_cases.csv"
docker run --rm --user 1000:1000 --network none -v "$W":/work \
  -e ZEN_ENV=harmony_demo -e PIPELINE_SRC_ROOT=/zenysis -e PIPELINE_UTILS_DIR=/zenysis/util/pipeline \
  -e PIPELINE_FEED_DIR=/work/feed -e PIPELINE_TMP_DIR=/work/tmp -w /zenysis \
  --entrypoint /bin/bash "$IMG" -c '
    source venv/bin/activate
    source util/pipeline/bash/common.sh
    SetupEnvForPyPy
    echo "step python: $(python -c "import sys, platform; print(platform.python_implementation(), sys.version.split()[0])")"
    start=$(date +%s%N)
    bash pipeline/harmony_demo/process/run/00_yellow_fever/10_process > /work/step.log 2>&1
    code=$?
    end=$(date +%s%N)
    echo "10_process: exit $code, wall $(( (end - start) / 1000000 )) ms"
    tail -3 /work/step.log
    ls -l /work/tmp | tail -n +2 | awk "{print \$5, \$9}"'
echo "work dir: $W"
