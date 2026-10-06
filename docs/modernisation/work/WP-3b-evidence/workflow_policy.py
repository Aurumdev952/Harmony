# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""WP-0f's workflow policy, re-runnable: exit 1 and list each breach.

- every `uses:` is pinned to a 40-hex commit SHA with the tag in a comment;
- every job runs on `ubuntu-24.04`;
- the workflow sets `permissions: {}` and each job its own grant, never `write-all`;
- no `${{ }}` inside a `run:` script (untrusted context goes through `env:`);
- `GH_TOKEN` is never set at workflow or job level, only on steps named
  "List changed files".

Usage: uv run docs/modernisation/work/WP-3b-evidence/workflow_policy.py [workflow ...]
"""

import re
import sys
from pathlib import Path

import yaml

PINNED = re.compile(r"^\s*uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s+#\s*v\S+\s*$")


def breaches(path: Path) -> list[str]:
    text = path.read_text()
    doc = yaml.safe_load(text)
    found = [
        f"{path}:{n}: action not pinned to a SHA with a tag comment"
        for n, line in enumerate(text.splitlines(), 1)
        if line.strip().startswith(("uses:", "- uses:"))
        and not PINNED.match(line.replace("- uses:", "uses:"))
    ]
    if doc.get("permissions") != {}:
        found.append(f"{path}: workflow permissions is not {{}}")
    if "GH_TOKEN" in (doc.get("env") or {}):
        found.append(f"{path}: workflow-level GH_TOKEN")
    for name, job in doc["jobs"].items():
        where = f"{path}: job {name}"
        if job.get("runs-on") != "ubuntu-24.04":
            found.append(f"{where}: runs-on {job.get('runs-on')!r}")
        perms = job.get("permissions")
        if not isinstance(perms, dict) or "write-all" in str(perms):
            found.append(f"{where}: permissions {perms!r}")
        if "GH_TOKEN" in (job.get("env") or {}):
            found.append(f"{where}: job-level GH_TOKEN")
        for step in job.get("steps", []):
            label = step.get("name", step.get("uses", "?"))
            if "${{" in step.get("run", ""):
                found.append(f"{where}, step {label!r}: ${{{{ }}}} inside run:")
            if "GH_TOKEN" in (step.get("env") or {}) and label != "List changed files":
                found.append(f"{where}, step {label!r}: GH_TOKEN")
    return found


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]] or sorted(
        Path(".github/workflows").glob("*.yml")
    )
    found = [b for p in paths for b in breaches(p)]
    print("\n".join(found) if found else f"policy OK ({len(paths)} workflows)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
