#!/usr/bin/env bash
# harmony_demo's 00_yellow_fever/10_process step, base image (PyPy) against this
# branch's image (CPython 3.13), three runs each at each size; outputs compared.
for rows in 12 100000 1000000; do
  for tag in base u3; do
    for run in 1 2 3; do
      out=$(bash "$(dirname "$0")/zeus_step.sh" "local/wp3b-infra3/harmony-etl-pipeline:$tag" "$rows" 2>&1)
      dir=$(sed -n 's/^work dir: //p' <<<"$out")
      py=$(sed -n 's/^step python: //p' <<<"$out")
      wall=$(grep -o 'wall [0-9]* ms' <<<"$out")
      sums=$(cd "$dir/tmp" && lz4cat processed_data.json.lz4 | sort | md5sum | cut -c1-8; md5sum locations.csv fields.csv | cut -c1-8 | tr '\n' ' ')
      echo "rows=$rows image=$tag ($py) run=$run $wall outputs=$(echo $sums)"
    done
  done
done
