#!/bin/bash -eu
# The merge that pipeline/harmony_demo/process/run/00_self_serve/10_process runs after
# process_csv_wrapper.py has written one set of outputs per source into $1.
set -o pipefail

source "${PIPELINE_SRC_ROOT}/util/pipeline/bash/common.sh"

PIPELINE_TMP_DIR="$1"
MergeDimensionsAndFields "${PIPELINE_TMP_DIR}"
cat "${PIPELINE_TMP_DIR}"/processed_data_*.json.lz4 > "${PIPELINE_TMP_DIR}/processed_data.json.lz4"
