"""Reads the two tables in INVENTORY.md.

Endpoint rows are ``| Method | Path | Server route | Called by | Coverage |``.
Relay rows are ``| Kind | Operation | Artifact | Coverage |``, one per GraphQL
operation the client sends through ``POST /api/graphql``.
Coverage is ``recorded`` (at least one case must exist) or ``deferred: <reason>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .cases import INVENTORY, REPO_ROOT

METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}
RELAY_KINDS = {"query", "mutation"}


@dataclass(frozen=True)
class Row:
    method: str
    path: str
    server_route: str
    called_by: str
    coverage: str
    line: int

    @property
    def route(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def deferred(self) -> bool:
        return self.coverage.startswith("deferred:")


@dataclass(frozen=True)
class RelayRow:
    kind: str
    operation: str
    artifact: str
    coverage: str
    line: int

    @property
    def deferred(self) -> bool:
        return self.coverage.startswith("deferred:")


def _cells(path: Path) -> list[tuple[int, list[str]]]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if line.startswith("|"):
            rows.append(
                (
                    number,
                    [c.strip().strip("`") for c in line.strip().strip("|").split("|")],
                )
            )
    return rows


def load_inventory(path: Path = INVENTORY) -> list[Row]:
    return [
        Row(*cells, number)
        for number, cells in _cells(path)
        if len(cells) == 5 and cells[0] in METHODS
    ]


def load_relay_operations(path: Path = INVENTORY) -> list[RelayRow]:
    return [
        RelayRow(*cells, number)
        for number, cells in _cells(path)
        if len(cells) == 4 and cells[0] in RELAY_KINDS
    ]


_OPERATION_KIND = re.compile(r'"operationKind":\s*"(query|mutation|subscription)"')
_OPERATION_NAME = re.compile(r'"name":\s*"(\w+)",\s*\n\s*"operationKind"')


def client_relay_operations() -> dict[str, tuple[str, str]]:
    """Every Relay operation artifact under web/client: artifact -> (kind, name)."""
    found = {}
    for path in sorted((REPO_ROOT / "web/client").rglob("__generated__/*.graphql.js")):
        text = path.read_text()
        kind = _OPERATION_KIND.search(text)
        if not kind:
            continue
        name = _OPERATION_NAME.search(text)
        found[str(path.relative_to(REPO_ROOT))] = (
            kind.group(1),
            name.group(1) if name else path.stem,
        )
    return found
