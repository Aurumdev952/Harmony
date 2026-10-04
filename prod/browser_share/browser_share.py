#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Browser share per deployment from nginx access logs (WP-0g).

Tailwind CSS v4 needs Chrome 111, Safari 16.4 or Firefox 128. This reports which
browsers each deployment's users run and the share of sessions below that line.

nginx logs no session id, so a session is one (client address, user agent) pair
with no gap longer than 30 minutes between requests. Client addresses are only
used as keys in memory and never printed.

    uv run prod/browser_share/browser_share.py --deployment rw access.log*
    docker logs <nginx> 2>/dev/null | uv run <this script> --deployment rw -

Without --deployment, each file's parent directory names its deployment.
"""

import argparse
import gzip
import io
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import cast

SESSION_GAP_SECONDS = 30 * 60
PHASE_7_GATE_PCT = 5.0


class Engine(StrEnum):
    BLINK = "blink"
    GECKO = "gecko"
    WEBKIT = "webkit"
    LEGACY = "legacy"
    UNKNOWN = "unknown"


BASELINE: dict[Engine, tuple[int, int]] = {
    Engine.BLINK: (111, 0),
    Engine.WEBKIT: (16, 4),
    Engine.GECKO: (128, 0),
}


@dataclass(frozen=True, slots=True)
class Browser:
    family: str
    major: int | None
    engine: Engine
    engine_version: tuple[int, int] | None

    @property
    def below_baseline(self) -> bool:
        if self.engine is Engine.LEGACY:
            return True
        floor = BASELINE.get(self.engine)
        return (
            floor is not None
            and self.engine_version is not None
            and self.engine_version < floor
        )


@dataclass(frozen=True, slots=True)
class Request:
    client: str
    epoch_seconds: int
    user_agent: str


# Matches nginx `combined` and the nginx-proxy `vhost` format, which adds a
# `$host ` prefix and an `$upstream_addr` suffix. `search` skips both prefixes
# and any `docker compose logs` line prefix.
_LINE = re.compile(
    r"(?P<client>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "
    r'"(?:[^"\\]|\\.)*" \d{3} \S+ '
    r'"(?:[^"\\]|\\.)*" "(?P<ua>(?:[^"\\]|\\.)*)"'
)

_AUTOMATED = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|go-http-client|okhttp|java/|"
    r"libwww|httpclient|axios|node-fetch|monitor|uptime|headless|lighthouse|"
    r"pingdom|facebookexternalhit|preview",
    re.IGNORECASE,
)

_IOS = re.compile(r"\((?:iPhone|iPad|iPod)[^)]*? OS (\d+)_(\d+)")
_IOS_BRANDS = (
    (re.compile(r"CriOS/(\d+)"), "Chrome iOS"),
    (re.compile(r"FxiOS/(\d+)"), "Firefox iOS"),
    (re.compile(r"EdgiOS/(\d+)"), "Edge iOS"),
)
_BLINK_BRANDS = (
    (re.compile(r"EdgA?/(\d+)"), "Edge"),
    (re.compile(r"OPR/(\d+)"), "Opera"),
    (re.compile(r"SamsungBrowser/(\d+)"), "Samsung Internet"),
    (re.compile(r"YaBrowser/(\d+)"), "Yandex"),
)
_CHROME = re.compile(r"Chrom(?:e|ium)/(\d+)")
_FIREFOX = re.compile(r"Firefox/(\d+)")
_SAFARI_VERSION = re.compile(r"Version/(\d+)(?:\.(\d+))?")
_EDGE_HTML = re.compile(r"Edge/(\d+)")
_IE = re.compile(r"MSIE (\d+)|Trident/.*rv:(\d+)")


def parse_line(line: str) -> Request | None:
    match = _LINE.search(line)
    if match is None:
        return None
    try:
        moment = datetime.strptime(match["time"], "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    return Request(match["client"], int(moment.timestamp()), match["ua"])


def is_automated(user_agent: str) -> bool:
    return user_agent in ("", "-") or _AUTOMATED.search(user_agent) is not None


def classify(user_agent: str) -> Browser:
    """Brand family and major for people; engine and version for the baseline.

    Every iOS browser is WebKit at the OS's Safari version, and Edge, Opera and
    Samsung Internet carry the real Chromium version in their `Chrome/` token.
    """
    if ios := _IOS.search(user_agent):
        safari = _SAFARI_VERSION.search(user_agent)
        webkit = (
            (int(safari[1]), int(safari[2] or 0))
            if safari
            else (int(ios[1]), int(ios[2]))
        )
        for pattern, family in _IOS_BRANDS:
            if brand := pattern.search(user_agent):
                return Browser(family, int(brand[1]), Engine.WEBKIT, webkit)
        family = "Mobile Safari" if safari else "iOS WebView"
        return Browser(family, webkit[0], Engine.WEBKIT, webkit)

    if ie := _IE.search(user_agent):
        return Browser("IE", int(ie[1] or ie[2]), Engine.LEGACY, None)
    if edge_html := _EDGE_HTML.search(user_agent):
        return Browser("Edge Legacy", int(edge_html[1]), Engine.LEGACY, None)
    if "Presto/" in user_agent:
        return Browser("Opera Presto", None, Engine.LEGACY, None)

    if chrome := _CHROME.search(user_agent):
        blink = (int(chrome[1]), 0)
        for pattern, family in _BLINK_BRANDS:
            if brand := pattern.search(user_agent):
                return Browser(family, int(brand[1]), Engine.BLINK, blink)
        family = "Chrome Android" if "Android" in user_agent else "Chrome"
        return Browser(family, blink[0], Engine.BLINK, blink)

    if firefox := _FIREFOX.search(user_agent):
        major = int(firefox[1])
        return Browser("Firefox", major, Engine.GECKO, (major, 0))

    if "Safari/" in user_agent and (safari := _SAFARI_VERSION.search(user_agent)):
        webkit = (int(safari[1]), int(safari[2] or 0))
        family = "Android Browser" if "Android" in user_agent else "Safari"
        return Browser(family, webkit[0], Engine.WEBKIT, webkit)

    return Browser("Other", None, Engine.UNKNOWN, None)


@dataclass(frozen=True, slots=True)
class BrowserShare:
    family: str
    major: int | None
    share_pct: float


@dataclass(frozen=True, slots=True)
class DeploymentReport:
    deployment: str
    sessions: int
    browsers: tuple[BrowserShare, ...]
    below_baseline_pct: float
    unknown_engine_pct: float
    automated_requests: int
    unparsed_lines: int


@dataclass(slots=True)
class _Tally:
    request_times: defaultdict[tuple[str, str], list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    automated_requests: int = 0
    unparsed_lines: int = 0

    def add(self, line: str) -> None:
        request = parse_line(line)
        if request is None:
            if line.strip():
                self.unparsed_lines += 1
        elif is_automated(request.user_agent):
            self.automated_requests += 1
        else:
            key = (request.client, request.user_agent)
            self.request_times[key].append(request.epoch_seconds)


def count_sessions(epoch_seconds: Iterable[int]) -> int:
    ordered = sorted(epoch_seconds)
    if not ordered:
        return 0
    gaps = sum(1 for a, b in pairwise(ordered) if b - a > SESSION_GAP_SECONDS)
    return 1 + gaps


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _report(deployment: str, tally: _Tally) -> DeploymentReport:
    by_browser: Counter[Browser] = Counter()
    for (_, user_agent), times in tally.request_times.items():
        by_browser[classify(user_agent)] += count_sessions(times)
    total = by_browser.total()

    by_brand: Counter[tuple[str, int | None]] = Counter()
    for browser, sessions in by_browser.items():
        by_brand[browser.family, browser.major] += sessions
    ranked = sorted(
        by_brand.items(),
        key=lambda item: (-item[1], item[0][0], -(item[0][1] or 0)),
    )
    return DeploymentReport(
        deployment=deployment,
        sessions=total,
        browsers=tuple(
            BrowserShare(family, major, _pct(sessions, total))
            for (family, major), sessions in ranked
        ),
        below_baseline_pct=_pct(
            sum(n for b, n in by_browser.items() if b.below_baseline), total
        ),
        unknown_engine_pct=_pct(
            sum(n for b, n in by_browser.items() if b.engine is Engine.UNKNOWN),
            total,
        ),
        automated_requests=tally.automated_requests,
        unparsed_lines=tally.unparsed_lines,
    )


def build_reports(
    sources: Iterable[tuple[str, Iterable[str]]],
) -> list[DeploymentReport]:
    """Reports per deployment, from (deployment, log lines) pairs in any order."""
    tallies: defaultdict[str, _Tally] = defaultdict(_Tally)
    for deployment, lines in sources:
        tally = tallies[deployment]
        for line in lines:
            tally.add(line)
    return [_report(name, tallies[name]) for name in sorted(tallies)]


def read_lines(path: str) -> Iterator[str]:
    """Lines of a plain or gzipped log file, or of stdin when `path` is `-`."""
    stdin = cast(io.BufferedReader, sys.stdin.buffer)
    with stdin if path == "-" else open(path, "rb") as raw:
        stream: io.BufferedReader | gzip.GzipFile = raw
        if raw.peek(2)[:2] == b"\x1f\x8b":
            stream = gzip.GzipFile(fileobj=raw)
        with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:
            yield from text


def format_text(report: DeploymentReport) -> str:
    excluded = (
        f"excluded {report.automated_requests} automated requests"
        f" and {report.unparsed_lines} unparsed lines"
    )
    gate = f"the {PHASE_7_GATE_PCT:.0f}% phase 7 gate"
    gate = (
        f"within {gate}"
        if report.below_baseline_pct <= PHASE_7_GATE_PCT
        else f"above {gate}; phase 7 needs a fallback plan"
    )
    rows = [
        f"Deployment {report.deployment}: {report.sessions} sessions; {excluded}",
        f"  {'family':<20} {'major':>5} {'share_pct':>9}",
        *(
            f"  {b.family:<20} {'-' if b.major is None else b.major:>5}"
            f" {b.share_pct:>9.1f}"
            for b in report.browsers
        ),
        f"  Below Chrome 111, Safari 16.4 or Firefox 128: "
        f"{report.below_baseline_pct:.1f}% of sessions ({gate})",
        f"  Unknown engine: {report.unknown_engine_pct:.1f}% of sessions",
    ]
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="access log, plain or gzipped; - for stdin",
    )
    parser.add_argument(
        "--deployment",
        help="deployment code for every PATH (default: parent directory)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    deployments: list[str] = []
    for path in args.paths:
        if args.deployment:
            deployments.append(args.deployment)
        elif path == "-":
            parser.error("reading stdin needs --deployment")
        else:
            deployments.append(Path(path).resolve().parent.name)

    reports = build_reports(
        (deployment, read_lines(path))
        for deployment, path in zip(deployments, args.paths, strict=True)
    )
    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2))
    else:
        print("\n\n".join(format_text(r) for r in reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
