#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Write requirements*.txt from pyproject.toml for the images that still use pip.

pyproject.toml is the source of truth. The images install these files with
`pip install -r` until WP-3b moves them to `uv sync --locked`, which deletes
this script and the files. Requirements are copied verbatim, so the images get
the same input they had before uv; the uv.lock overrides do not apply to them.

    uv run docker/export_requirements.py          # rewrite the files
    uv run docker/export_requirements.py --check  # exit 1 if any file is stale
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "# Generated from pyproject.toml by `make requirements`; do not edit.\n"
    "# The images install this with pip until WP-3b moves them to uv.\n"
)
TARGETS = {
    "requirements.txt": None,
    "requirements-web.txt": "web",
    "requirements-pipeline.txt": "pipeline",
    "requirements-dev.txt": "dev",
}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def render(requirements: list[str], sources: dict[str, dict[str, str]]) -> str:
    lines = []
    for requirement in requirements:
        match = NAME.match(requirement)
        name = match.group(0) if match else ""
        source = sources.get(name)
        if source is not None:
            lines.append(f"-e git+{source['git']}@{source['rev']}#egg={name}")
        else:
            lines.append(requirement)
    return HEADER + "\n".join(lines) + "\n"


def expected_files(root: Path) -> dict[Path, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    sources = pyproject["tool"]["uv"]["sources"]
    groups = pyproject["dependency-groups"]
    return {
        root / filename: render(
            pyproject["project"]["dependencies"] if group is None else groups[group],
            sources,
        )
        for filename, group in TARGETS.items()
    }


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="report stale files and exit 1"
    )
    args = parser.parse_args(argv)
    stale = []
    for path, content in expected_files(root).items():
        current = path.read_text() if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path.name)
        else:
            path.write_text(content)
    if stale:
        print(f"stale, run `make requirements`: {', '.join(stale)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
