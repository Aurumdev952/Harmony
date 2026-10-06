#!/bin/bash
# digest.sh <work>: md5 (first 12 hex) of every output, decompressed, byte for byte.
cd "$1" || exit 1
d=20261006
for s in self_serve yellow_fever; do
  t=tmp/$s/$d
  printf '%s %s ' "$s.rows" "$(lz4cat "$t/processed_data.json.lz4" | md5sum | cut -c1-12)"
  printf '%s %s ' "$s.locations" "$(md5sum < "$t/locations.csv" | cut -c1-12)"
  printf '%s %s ' "$s.fields" "$(md5sum < "$t/fields.csv" | cut -c1-12)"
  o=out/$s/$d
  printf '%s %s ' "$s.druid" "$(cat "$o"/processed_rows.*.json.gz | gzip -dc | md5sum | cut -c1-12)"
  printf '%s %s ' "$s.digest" "$(md5sum < "$o/metadata_digest_file.csv" | cut -c1-12)"
done
echo
