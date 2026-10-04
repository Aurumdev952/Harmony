#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Browser share per deployment from nginx access logs (WP-0g).

Tailwind CSS v4 needs Chrome 111, Safari 16.4 or Firefox 128. This reports which
browsers each deployment's users run and the share of sessions below that line.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
