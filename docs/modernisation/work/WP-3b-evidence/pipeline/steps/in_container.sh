#!/bin/bash
# Inside a pipeline image: the three harmony_demo per-row process steps in Zeus
# order, as the entrypoint runs them (venv activated, then the step file).
cd /zenysis || exit 1
source venv/bin/activate
export ZEN_ENV=harmony_demo PIPELINE_SRC_ROOT=/zenysis PIPELINE_UTILS_DIR=/zenysis/util/pipeline
export PIPELINE_OUT_ROOT=/work PIPELINE_DATE=20261006
export PIPELINE_BIN_DIR=/zenysis/pipeline/harmony_demo/process
STEPS=/zenysis/pipeline/harmony_demo/process/run

# The interpreter a step's `python` resolves to, after the step's own setup.
step_python=$(
  source util/pipeline/bash/common.sh
  if declare -F SetupEnvForPyPy > /dev/null; then SetupEnvForPyPy > /dev/null; fi
  python -c 'import platform, sys; print(platform.python_implementation(), sys.version.split()[0])'
)
echo "step_python=${step_python// /_}"

run() {
  local name="$1" source="$2" script="$3"
  export PIPELINE_FEED_DIR="/work/feed/$source/$PIPELINE_DATE"
  export PIPELINE_TMP_DIR="/work/tmp/$source/$PIPELINE_DATE"
  mkdir -p "$PIPELINE_TMP_DIR"
  python /probe/measure.py "$name" "$script" "/work/$name.log" || exit 1
}

mkdir -p /work/out/self_serve/$PIPELINE_DATE /work/out/yellow_fever/$PIPELINE_DATE
run self_serve self_serve "$STEPS/00_self_serve/10_process"
run process_csv yellow_fever "$STEPS/00_yellow_fever/10_process"
run fill_dimension_data shared "$STEPS/90_shared/10_fill_dimension_data.abort_fail"
grep -c 'venv_pypy3' /work/*.log | sed 's/^/pypy_warnings /'
