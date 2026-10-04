#!/usr/bin/env bash
# Installs every marketplace and plugin that .claude/settings.json declares, so each
# migration agent has its skills. Run once per machine after accepting workspace trust.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SETTINGS="$ROOT/.claude/settings.json"

python3 - "$SETTINGS" <<'EOF' | while read -r kind value; do
import json, sys
s = json.load(open(sys.argv[1]))
for name, entry in s.get("extraKnownMarketplaces", {}).items():
    src = entry["source"]
    print("marketplace", src.get("repo") or src.get("url"))
for plugin, on in s.get("enabledPlugins", {}).items():
    if on:
        print("plugin", plugin)
EOF
  case "$kind" in
    marketplace) claude plugin marketplace add "$value" || true ;;
    plugin) claude plugin install "$value" --scope project || echo "WARN: could not install $value" >&2 ;;
  esac
done

claude plugin list
