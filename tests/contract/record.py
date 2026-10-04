"""Record or check API contract cases.

    tests/contract/stack/stack.sh up
    eval "$(tests/contract/stack/stack.sh env)"
    uv run --no-project --with requests python -m tests.contract.record            # record all
    uv run --no-project --with requests python -m tests.contract.record --check    # compare only
    uv run --no-project --with requests python -m tests.contract.record --dry-run  # no network

--dry-run loads every case, checks it against INVENTORY.md and prints what
would be sent, without touching the network.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from .cases import RECORDINGS_DIR, Case, compare, load_cases, placeholders, recording_path
from .inventory import load_inventory


def dry_run(cases: list[Case]) -> int:
    routes = {row.route for row in load_inventory()}
    captured: set[str] = set()
    problems = 0
    for case in cases:
        flags = []
        if case.route not in routes:
            flags.append("route not in INVENTORY.md")
        missing = [p for p in placeholders(case) if p not in captured]
        if missing:
            flags.append(f"needs uncaptured {missing}")
        if not recording_path(case.id).exists():
            flags.append("no recording yet")
        captured.update(case.capture)
        body = "multipart" if case.files else ("json" if case.body is not None else "-")
        print(f"{case.id:48} {case.session:9} {case.method:6} {case.path} query={dict(case.query)} body={body}")
        for flag in flags:
            print(f"    ! {flag}")
        problems += any(f != "no recording yet" for f in flags)
    print(f"{len(cases)} cases, {problems} with problems")
    return 1 if problems else 0


def live(cases: list[Case], base_url: str, check: bool, selected: set[str]) -> int:
    from .runner import Credentials, Runner, SkipCase

    runner = Runner(base_url.rstrip("/"), Credentials.from_env())
    failures = 0
    for case in cases:
        try:
            observed = runner.run(case)
        except SkipCase as exc:
            print(f"SKIP {case.id}: {exc}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide the rest
            print(f"ERROR {case.id}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        if case.id not in selected:
            continue
        path = recording_path(case.id)
        if check:
            if not path.exists():
                print(f"MISSING {case.id}")
                failures += 1
                continue
            problems = compare(case, json.loads(path.read_text()), observed)
            print(f"{'ok  ' if not problems else 'FAIL'} {case.id}")
            for p in problems:
                print(f"     {p}")
            failures += bool(problems)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"id": case.id, "route": case.route, **observed}
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(f"rec  {case.id} {observed['status']} {observed['content_type']}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("CONTRACT_BASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="validate and print cases; no network")
    parser.add_argument("--check", action="store_true", help="compare against recordings; write nothing")
    parser.add_argument("--only", help="glob on case id; earlier cases still run so captures exist")
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.dry_run:
        return dry_run(cases)
    if not args.base_url:
        parser.error("--base-url or CONTRACT_BASE_URL is required unless --dry-run")
    selected = {c.id for c in cases if not args.only or fnmatch.fnmatch(c.id, args.only)}
    if args.only:
        last = max((i for i, c in enumerate(cases) if c.id in selected), default=-1)
        cases = cases[: last + 1]
    status = live(cases, args.base_url, args.check, selected)
    if not args.check and not args.only:
        known = {c.id for c in cases}
        for stale in sorted(Path(RECORDINGS_DIR).glob("*.json")):
            if stale.stem not in known:
                stale.unlink()
                print(f"removed stale recording {stale.name}")
    return status


if __name__ == "__main__":
    sys.exit(main())
