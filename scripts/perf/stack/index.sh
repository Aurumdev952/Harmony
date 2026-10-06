#!/bin/bash
# Runs inside the perf stack's `indexer` service: stages the pipeline output the
# way pipeline/harmony_demo/index/run/00_druid/00_index expects it, then runs that
# step's commands. Only --concurrent_subtasks differs (one file needs one subtask).
set -euo pipefail
cd /src

share=/home/share
current="${share}/data/harmony_demo/yellow_fever/current"
mkdir -p "${current}" "${share}/data/logs/druid_indexing/hash"
rm -f "${current}"/processed_rows.*
cp /pipeline-out/processed_rows.*.json.gz "${current}/"

python db/druid/indexing/scripts/run_native_indexing.py \
  --data_files="${share}/data/harmony_demo/*/current/processed_rows.*" \
  --task_id_file=/tmp/task_id \
  --task_hash_dir "${share}/data/logs/druid_indexing/hash" \
  --local_server_shared_folder "${share}" \
  --min_data_date='1970-01-01' \
  --concurrent_subtasks 1 \
  "$@"

if [[ ! -f /tmp/task_id ]]; then
  echo 'perf index: no task created (the datasource already holds these files)'
  exit 0
fi
python db/druid/indexing/scripts/fetch_status.py \
  --task_id="$(cat /tmp/task_id)" \
  --block_until_completed
