"""Consistency checks between INVENTORY.md, the cases and the recordings.

Each function returns a list of problems (empty when consistent).
test_catalogue.py asserts each one, and ``record.py --dry-run`` prints them,
so both read the same rules.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .cases import (
    RECORDINGS_DIR,
    RELAY_PREFIX,
    Case,
    captures_of,
    placeholders,
    recording_path,
)
from .inventory import RelayRow, Row, client_relay_operations

# Patterns that would mean a value, not a shape, reached a fixture (SPEC INV-6).
LEAKS = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+"  # email addresses
    r"|eyJ[\w-]{8,}"  # JWTs
    r"|[0-9a-f]{32,}"  # hex digests and tokens
)


def duplicate_routes(rows: list[Row]) -> list[str]:
    return [route for route, n in Counter(r.route for r in rows).items() if n > 1]


def cases_without_a_row(cases: list[Case], rows: list[Row]) -> list[str]:
    routes = {r.route for r in rows}
    return [
        f"{c.id}: {c.route} is not in INVENTORY.md"
        for c in cases
        if c.route not in routes
    ]


def coverage_problems(cases: list[Case], rows: list[Row]) -> list[str]:
    covered = {c.route for c in cases}
    problems = []
    for r in rows:
        if r.coverage == "recorded" and r.route not in covered:
            problems.append(f"{r.route}: marked recorded but has no case")
        elif r.deferred and r.route in covered:
            problems.append(f"{r.route}: deferred but has a case")
        elif r.coverage != "recorded" and not re.match(r"deferred: \S", r.coverage):
            problems.append(
                f"{r.route}: coverage must be 'recorded' or 'deferred: <reason>'"
            )
    return problems


def relay_problems(cases: list[Case], relay_rows: list[RelayRow]) -> list[str]:
    """Every Relay operation in web/client is listed once; recorded ones have a
    case that sends that operation's text, deferred ones have none."""
    sent = {
        c.body["query"].removeprefix(RELAY_PREFIX)
        for c in cases
        if isinstance(c.body, dict)
        and str(c.body.get("query", "")).startswith(RELAY_PREFIX)
    }
    operations = client_relay_operations()
    listed = {r.artifact: r for r in relay_rows}
    problems = [
        f"{a}: Relay operation missing from INVENTORY.md"
        for a in sorted(set(operations) - set(listed))
    ]
    problems += [
        f"{a}: listed but not a client Relay operation"
        for a in sorted(set(listed) - set(operations))
    ]
    for artifact, row in sorted(listed.items()):
        if row.coverage == "recorded" and artifact not in sent:
            problems.append(f"{row.operation}: marked recorded but no case sends it")
        elif row.deferred and artifact in sent:
            problems.append(f"{row.operation}: deferred but a case sends it")
        elif row.coverage != "recorded" and not re.match(r"deferred: \S", row.coverage):
            problems.append(
                f"{row.operation}: coverage must be 'recorded' or 'deferred: <reason>'"
            )
    problems += [
        f"{a}: a case sends it but INVENTORY.md does not list it"
        for a in sorted(sent - set(listed))
    ]
    return problems


def capture_order_problems(cases: list[Case]) -> list[str]:
    captured: set[str] = set()
    problems = []
    for case in cases:
        problems += [
            f"{case.id}: uses {p} before any case captures it"
            for p in placeholders(case)
            if p not in captured
        ]
        captured.update(captures_of(case))
    return problems


def recording_problems(
    cases: list[Case], recordings_dir: Path = RECORDINGS_DIR
) -> list[str]:
    ids = {c.id for c in cases}
    on_disk = {p.stem for p in recordings_dir.glob("*.json")}
    problems = [f"{i}: no recording" for i in sorted(ids - on_disk)]
    problems += [f"{i}: recording without a case" for i in sorted(on_disk - ids)]
    for case in cases:
        path = recording_path(case.id, recordings_dir)
        if path.exists():
            recording = json.loads(path.read_text())
            if (recording["id"], recording["route"]) != (case.id, case.route):
                problems.append(
                    f"{case.id}: recording names {recording['id']} / {recording['route']}"
                )
    return problems


def leak_problems(recordings_dir: Path = RECORDINGS_DIR) -> list[str]:
    return [
        f"{p.name}: {match}"
        for p in sorted(recordings_dir.glob("*.json"))
        for match in LEAKS.findall(p.read_text())
    ]


def all_problems(
    cases: list[Case], rows: list[Row], relay_rows: list[RelayRow]
) -> list[str]:
    return [
        *duplicate_routes(rows),
        *cases_without_a_row(cases, rows),
        *coverage_problems(cases, rows),
        *relay_problems(cases, relay_rows),
        *capture_order_problems(cases),
        *recording_problems(cases),
        *leak_problems(),
    ]
