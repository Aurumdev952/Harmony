#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Browser share for one deployment from its nginx access logs (WP-0g).

Tailwind CSS v4 needs Chrome 111, Safari 16.4 or Firefox 128. This reports which
browsers a deployment's users run and the share of sessions below that line.

nginx logs no session id, so a session is one (client address, user agent) pair
with no gap longer than 30 minutes between requests. Client addresses are only
used as keys in memory and never printed.

    docker logs <nginx> 2>/dev/null | uv run <this script> --deployment rw -
    uv run prod/browser_share/browser_share.py --deployment rw access.log*

Exits 1 when no browser sessions were found, so the gate was not evaluated.
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
from itertools import chain, pairwise
from typing import IO, cast

SESSION_GAP_SECONDS = 30 * 60
PHASE_7_GATE_PCT = 5


class Engine(StrEnum):
    BLINK = "blink"
    GECKO = "gecko"
    WEBKIT = "webkit"
    LEGACY = "legacy"
    UNKNOWN = "unknown"


class Gate(StrEnum):
    WITHIN = "within"
    ABOVE = "above"
    NOT_EVALUATED = "not evaluated"


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


# Anchored, so a long line that does not match fails in linear time. Accepts an
# optional `docker compose logs` prefix and the `$host ` that nginx-proxy's
# `vhost` format puts before the `combined` fields.
_LINE = re.compile(
    r"(?:[\w.-]+ +\| )?"
    r"(?:\S+ )?"
    r"(?P<client>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "
    r'"(?:[^"\\]|\\.)*" \d{3} \S+ '
    r'"(?:[^"\\]|\\.)*" "(?P<ua>(?:[^"\\]|\\.)*)"'
)

_AUTOMATED = re.compile(
    r"bot[/;-]|\bbot\b|crawl|spider|slurp|curl|wget|python|go-http-client|okhttp|"
    r"java/|libwww|httpclient|axios|node-fetch|monitor|uptime|headless|lighthouse|"
    r"pingdom|facebookexternalhit|preview",
    re.IGNORECASE,
)

# Bounded so int() never sees a number past its digit limit.
_N = r"(\d{1,5})(?!\d)"

_IOS = re.compile(rf"\((?:iPhone|iPad|iPod)[^)]*? OS {_N}_{_N}")
_IOS_BRANDS = (
    (re.compile(rf"CriOS/{_N}"), "Chrome iOS"),
    (re.compile(rf"FxiOS/{_N}"), "Firefox iOS"),
    (re.compile(rf"EdgiOS/{_N}"), "Edge iOS"),
)
_BLINK_BRANDS = (
    (re.compile(rf"EdgA?/{_N}"), "Edge"),
    (re.compile(rf"OPR/{_N}"), "Opera"),
    (re.compile(rf"SamsungBrowser/{_N}"), "Samsung Internet"),
    (re.compile(rf"UCBrowser/{_N}"), "UC Browser"),
    (re.compile(rf"YaBrowser/{_N}"), "Yandex"),
)
_CHROME = re.compile(rf"Chrom(?:e|ium)/{_N}")
_FIREFOX = re.compile(rf"Firefox/{_N}")
_SAFARI_VERSION = re.compile(rf"Version/{_N}(?:\.{_N})?")
_EDGE_HTML = re.compile(rf"Edge/{_N}")
_IE = re.compile(rf"MSIE {_N}|Trident/[^)]*rv:{_N}")


def parse_line(line: str) -> Request | None:
    match = _LINE.match(line)
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

    Every iOS browser is WebKit, and Edge, Opera, Samsung Internet and UC Browser
    carry the real Chromium version in their `Chrome/` token.
    """
    if ios := _IOS.search(user_agent):
        # Safari 26 freezes the OS token at 18_6; Edge iOS truncates Version/.
        webkit = (int(ios[1]), int(ios[2]))
        if safari := _SAFARI_VERSION.search(user_agent):
            webkit = max(webkit, (int(safari[1]), int(safari[2] or 0)))
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


def phase_7_gate(below: int, total: int) -> Gate:
    if total == 0:
        return Gate.NOT_EVALUATED
    if below * 100 > PHASE_7_GATE_PCT * total:
        return Gate.ABOVE
    return Gate.WITHIN


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
    below_baseline_sessions: int
    below_baseline_pct: float
    unknown_engine_pct: float
    automated_requests: int
    unparsed_lines: int
    phase_7_gate: Gate


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


def build_report(deployment: str, lines: Iterable[str]) -> DeploymentReport:
    """Report for one deployment from its log lines, in any order."""
    tally = _Tally()
    for line in lines:
        tally.add(line)

    by_browser: Counter[Browser] = Counter()
    for (_, user_agent), times in tally.request_times.items():
        by_browser[classify(user_agent)] += count_sessions(times)
    total = by_browser.total()
    below = sum(n for b, n in by_browser.items() if b.below_baseline)
    unknown = sum(n for b, n in by_browser.items() if b.engine is Engine.UNKNOWN)

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
        below_baseline_sessions=below,
        below_baseline_pct=_pct(below, total),
        unknown_engine_pct=_pct(unknown, total),
        automated_requests=tally.automated_requests,
        unparsed_lines=tally.unparsed_lines,
        phase_7_gate=phase_7_gate(below, total),
    )


def read_lines(path: str) -> Iterator[str]:
    """Lines of a plain or gzipped log file, or of stdin when `path` is `-`."""
    stdin = cast(io.BufferedReader, sys.stdin.buffer)
    with stdin if path == "-" else open(path, "rb") as raw:
        # mypy 1.3's typeshed does not count GzipFile as IO[bytes].
        stream: IO[bytes] = raw
        if raw.peek(2)[:2] == b"\x1f\x8b":
            stream = cast(IO[bytes], gzip.GzipFile(fileobj=raw))
        with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:
            yield from text


def format_text(report: DeploymentReport) -> str:
    rows = [
        f"Deployment {report.deployment}: {report.sessions} sessions;"
        f" excluded {report.automated_requests} automated requests"
        f" and {report.unparsed_lines} unparsed lines",
    ]
    if report.phase_7_gate is Gate.NOT_EVALUATED:
        rows.append(
            "  Phase 7 gate not evaluated: no browser sessions found."
            " Check that the input is this deployment's nginx access log."
        )
        return "\n".join(rows)

    gate = f"{report.phase_7_gate} the {PHASE_7_GATE_PCT}% phase 7 gate"
    if report.phase_7_gate is Gate.ABOVE:
        gate += "; phase 7 needs a fallback plan"
    rows += [
        f"  {'family':<20} {'major':>5} {'share_pct':>9}",
        *(
            f"  {b.family:<20} {'-' if b.major is None else b.major:>5}"
            f" {b.share_pct:>9.1f}"
            for b in report.browsers
        ),
        "  Below Chrome 111, Safari 16.4 or Firefox 128:"
        f" {report.below_baseline_sessions} of {report.sessions} sessions,"
        f" {report.below_baseline_pct:.1f}% ({gate})",
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
        "--deployment", required=True, help="deployment code, for example rw"
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    try:
        report = build_report(
            args.deployment, chain.from_iterable(map(read_lines, args.paths))
        )
    except OSError as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(format_text(report))
    return 1 if report.phase_7_gate is Gate.NOT_EVALUATED else 0


if __name__ == "__main__":
    raise SystemExit(main())
