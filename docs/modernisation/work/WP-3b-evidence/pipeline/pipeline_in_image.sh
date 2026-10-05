#!/usr/bin/env bash
# The pipeline fixture suite inside a pipeline image, on the image's venv: the repo's
# tests/ are mounted read-only, and uv layers only pytest and hypothesis (test tools)
# over the image's /zenysis/venv, so the steps run with the image's packages.
# Runs as uid 1000, the user docker-compose.pipeline.yaml runs the pipeline as.
# Usage: pipeline_in_image.sh <tree> <image> [pytest args]
TREE="$1"; IMG="$2"; shift 2
docker run --rm --user 1000:1000 \
  -v "$TREE/tests":/zenysis/tests:ro \
  -v "${UV_BIN:?set UV_BIN to a static uv 0.12.23 binary}":/usr/local/bin/uv:ro \
  -e UV_CACHE_DIR=/tmp/uv-cache -e CI=true -e ZEN_ENV=harmony_demo \
  -e HYPOTHESIS_STORAGE_DIRECTORY=/tmp/hypothesis -w /zenysis \
  --entrypoint /bin/bash "$IMG" -c '
    with_tools=(uv run -q --no-project --python /zenysis/venv/bin/python --with pytest==8.4.2 --with hypothesis==6.91.0)
    "${with_tools[@]}" python -c "import sys, pandas; print(sys.version.split()[0], sys.executable, pandas.__file__)"
    start=$(date +%s%N)
    "${with_tools[@]}" python -m pytest --rootdir /zenysis -p no:cacheprovider -q tests/pipeline "$@"
    code=$?
    end=$(date +%s%N)
    echo "exit $code, wall $(( (end - start) / 1000000 )) ms"
    exit $code' bash "$@"
