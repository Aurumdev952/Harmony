"""Reads the endpoint table in INVENTORY.md.

Each table row is ``| Method | Path | Server route | Called by | Coverage |``.
Coverage is ``recorded`` (at least one case must exist for the route) or
``deferred: <reason>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cases import INVENTORY

METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


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


def load_inventory(path: Path = INVENTORY) -> list[Row]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] not in METHODS:
            continue
        method, route_path, server_route, called_by, coverage = cells
        rows.append(Row(method, route_path.strip("`"), server_route, called_by, coverage, number))
    return rows
