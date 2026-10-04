#!/usr/bin/env bash
# Refreshes the vendor-published skills copied into .claude/skills/.
# Usage: scripts/agents/update_vendored_skills.sh
# Review the diff before committing: vendored skills become agent instructions.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DEST="$ROOT/.claude/skills"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# repo|branch|sparse paths|copy spec (src:dest[:license])
SOURCES=(
  "heroui-inc/heroui|v3|/skills/ /LICENSE|skills/heroui-react:heroui-react"
  "fastapi/fastapi|master|/fastapi/.agents/ /LICENSE|fastapi/.agents/skills/fastapi:fastapi:LICENSE"
  "maplibre/maplibre-agent-skills|main|/skills/ /LICENSE.md /NOTICE|skills/maplibre-v6-migration:maplibre-v6-migration:LICENSE.md,NOTICE skills/maplibre-source-wiring:maplibre-source-wiring:LICENSE.md,NOTICE"
  "TanStack/router|main|/packages/router-core/skills/ /packages/router-plugin/skills/ /packages/react-router/skills/ /LICENSE|packages/router-core/skills/router-core:router-core:LICENSE packages/router-plugin/skills/router-plugin:router-plugin:LICENSE packages/react-router/skills/compositions/router-query:router-query:LICENSE"
)

LOCK="$DEST/VENDORED.lock"
: > "$LOCK.new"
for entry in "${SOURCES[@]}"; do
  IFS='|' read -r repo branch sparse copies <<<"$entry"
  dir="$WORK/${repo//\//_}"
  git clone -q --depth 1 --filter=blob:none --no-checkout -b "$branch" "https://github.com/$repo.git" "$dir"
  # shellcheck disable=SC2086
  git -C "$dir" sparse-checkout set --no-cone $sparse
  git -C "$dir" checkout -q
  sha="$(git -C "$dir" rev-parse HEAD)"
  for spec in $copies; do
    IFS=':' read -r src name licenses <<<"$spec"
    rm -rf "${DEST:?}/$name"
    cp -r "$dir/$src" "$DEST/$name"
    for lic in ${licenses//,/ }; do cp "$dir/$lic" "$DEST/$name/"; done
    echo "$name $repo $sha" >> "$LOCK.new"
  done
done
mv "$LOCK.new" "$LOCK"
echo "Updated. Review with: git diff -- .claude/skills"
