"""Record API contract cases, or show what would be recorded.

    tests/contract/stack/stack.sh up
    eval "$(tests/contract/stack/stack.sh env)"
    uv run --locked python -m tests.contract.record            # record all
    uv run --locked python -m tests.contract.record --only 'dashboard.*'
    uv run --locked python -m tests.contract.record --dry-run  # no network

Replaying is pytest's job: ``pytest tests/contract -m stack``.

--dry-run prints every request it would send and the catalogue problems
test_catalogue.py would report, without touching the network.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys

from . import catalogue
from .cases import RECORDINGS_DIR, Case, load_cases, recording_path
from .inventory import load_inventory, load_relay_operations


def dry_run(cases: list[Case]) -> int:
    for case in cases:
        body = "multipart" if case.files else ("json" if case.body is not None else "-")
        print(
            f"{case.id:56} {case.session:14} {case.method:6} {case.path} query={dict(case.query)} body={body}"
        )
    problems = catalogue.all_problems(cases, load_inventory(), load_relay_operations())
    for problem in problems:
        print(f"! {problem}")
    empty = catalogue.always_empty_lists(cases)
    print(f"lists empty in every recording, so no item shape is pinned ({len(empty)}):")
    for operation, paths in empty.items():
        print(f"  {operation}: {', '.join(paths)}")
    print(f"{len(cases)} cases, {len(problems)} problems")
    return 1 if problems else 0


def record(cases: list[Case], base_url: str, selected: set[str]) -> int:
    from .runner import Credentials, Runner, SkipCase

    runner = Runner(base_url.rstrip("/"), Credentials.from_env())
    failures = 0
    for case in cases:
        try:
            observed = runner.run(case, recording=True)
        except SkipCase as exc:
            print(f"SKIP {case.id}: {exc}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide the rest
            print(f"ERROR {case.id}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        broken = observed.get("missing_pins", []) + observed.get("capture_errors", [])
        if broken:
            print(f"ERROR {case.id}: {broken}")
            failures += 1
            continue
        if case.id in selected:
            record = {"id": case.id, "route": case.route, **observed}
            recording_path(case.id).write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n"
            )
            print(f"rec  {case.id} {observed['status']} {observed['content_type']}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default=os.environ.get("CONTRACT_BASE_URL"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print requests and catalogue problems; no network",
    )
    parser.add_argument(
        "--only", help="glob on case id to record; every case still runs"
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.dry_run:
        return dry_run(cases)
    if not args.base_url:
        parser.error("--base-url or CONTRACT_BASE_URL is required unless --dry-run")
    # Every case still runs, so captures exist and later cases clean up what
    # earlier ones created; --only limits what is written.
    selected = {
        c.id for c in cases if not args.only or fnmatch.fnmatch(c.id, args.only)
    }
    RECORDINGS_DIR.mkdir(exist_ok=True)
    status = record(cases, args.base_url, selected)
    if not args.only:
        known = {c.id for c in cases}
        for stale in sorted(RECORDINGS_DIR.glob("*.json")):
            if stale.stem not in known:
                stale.unlink()
                print(f"removed stale recording {stale.name}")
    return status


if __name__ == "__main__":
    sys.exit(main())
