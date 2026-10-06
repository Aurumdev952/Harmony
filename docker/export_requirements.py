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
from typing import Any

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
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ExportError(Exception):
    pass


def normalise(name: str) -> str:
    """PEP 503 name normalisation, as uv applies it to [tool.uv.sources] keys."""
    return re.sub(r"[-_.]+", "-", name).lower()


def project_name(requirement: str) -> str:
    match = NAME.match(requirement)
    return match.group(0) if match else ""


def requirement_name(requirement: str) -> str:
    return normalise(project_name(requirement))


def render(requirements: list[str], sources: dict[str, dict[str, str]]) -> str:
    lines = []
    for requirement in requirements:
        source = sources.get(requirement_name(requirement))
        if source is not None:
            egg = project_name(requirement)
            lines.append(f"-e git+{source['git']}@{source['rev']}#egg={egg}")
        else:
            lines.append(requirement)
    return HEADER + "\n".join(lines) + "\n"


def git_sources(
    pyproject: dict[str, Any], requirements: list[str]
) -> dict[str, dict[str, str]]:
    sources = {
        normalise(name): source
        for name, source in pyproject["tool"]["uv"]["sources"].items()
    }
    for name, source in sources.items():
        if not COMMIT_SHA.match(source.get("rev", "")):
            raise ExportError(
                f"[tool.uv.sources] {name}: rev must be a 40-character commit SHA"
            )
    unused = set(sources) - {requirement_name(r) for r in requirements}
    if unused:
        raise ExportError(
            f"[tool.uv.sources] not used by any requirement: {', '.join(sorted(unused))}"
        )
    return sources


def expected_files(root: Path) -> dict[Path, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    groups = pyproject["dependency-groups"]
    lists = {
        filename: pyproject["project"]["dependencies"]
        if group is None
        else groups[group]
        for filename, group in TARGETS.items()
    }
    sources = git_sources(pyproject, [r for group in lists.values() for r in group])
    return {
        root / filename: render(requirements, sources)
        for filename, requirements in lists.items()
    }


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="report stale files and exit 1"
    )
    args = parser.parse_args(argv)
    try:
        expected = expected_files(root)
    except ExportError as error:
        print(error, file=sys.stderr)
        return 2
    stale = []
    for path, content in expected.items():
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
