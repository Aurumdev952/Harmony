#!/usr/bin/env bash
# perf7_in_image.sh <branch-image> <base-image>: core's parse benchmark (core/parse_bench.py)
# inside the images, as uid 1000 and with no network. The branch image parses with
# db.druid.json_stream; the base image (CPython 3.8) with ijson-bigint's yajl2_c.
set -euo pipefail
BRANCH="$1"
BASE="$2"
HERE=$(cd "$(dirname "$0")" && pwd -P)
DATA=$(mktemp -d)
trap 'rm -rf "$DATA"' EXIT
chmod 777 "$DATA"
bench() {
  docker run --rm --user 1000 --network none --entrypoint python -w /zenysis \
    -v "$HERE/core/parse_bench.py":/bench.py:ro -v "$DATA":/tmp/core3b "$@"
}
bench "$BRANCH" /bench.py make
echo "variant	shape	rows	best_s	peak_rss_mb	python"
for shape in array dict; do
  bench "$BASE" /bench.py run ijson_yajl2_c "$shape"
  bench "$BRANCH" /bench.py run client "$shape"
done
echo "installed JSON stream parsers in the branch image (expect none):"
docker run --rm --network none --entrypoint python "$BRANCH" -c \
  "import importlib.util as u; print([m for m in ('ijson', 'msgspec', 'orjson', 'yajl') if u.find_spec(m)])"
