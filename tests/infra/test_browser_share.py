import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prod" / "browser_share"))

from browser_share import (  # noqa: E402
    Browser,
    Engine,
    classify,
    is_automated,
    parse_line,
)

BLINK_TAIL = "AppleWebKit/537.36 (KHTML, like Gecko)"
WEBKIT_TAIL = "AppleWebKit/605.1.15 (KHTML, like Gecko)"
WINDOWS = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {BLINK_TAIL}"
MAC = f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) {WEBKIT_TAIL}"
ANDROID = f"Mozilla/5.0 (Linux; Android 13; K) {BLINK_TAIL}"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS {os} like Mac OS X) " + WEBKIT_TAIL


def chrome(major: int) -> str:
    return f"{WINDOWS} Chrome/{major}.0.0.0 Safari/537.36"


def firefox(major: int) -> str:
    platform = f"Windows NT 10.0; Win64; x64; rv:{major}.0"
    return f"Mozilla/5.0 ({platform}) Gecko/20100101 Firefox/{major}.0"


def safari(version: str) -> str:
    return f"{MAC} Version/{version} Safari/605.1.15"


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (chrome(126), Browser("Chrome", 126, Engine.BLINK, (126, 0))),
        (
            f"{chrome(125)} Edg/125.0.0.0",
            Browser("Edge", 125, Engine.BLINK, (125, 0)),
        ),
        (
            f"{chrome(124)} OPR/110.0.0.0",
            Browser("Opera", 110, Engine.BLINK, (124, 0)),
        ),
        (
            f"{ANDROID} SamsungBrowser/21.0 Chrome/110.0.5481.154 Mobile Safari/537.36",
            Browser("Samsung Internet", 21, Engine.BLINK, (110, 0)),
        ),
        (
            f"{ANDROID} Chrome/126.0.0.0 Mobile Safari/537.36",
            Browser("Chrome Android", 126, Engine.BLINK, (126, 0)),
        ),
        (firefox(115), Browser("Firefox", 115, Engine.GECKO, (115, 0))),
        (safari("16.3"), Browser("Safari", 16, Engine.WEBKIT, (16, 3))),
        (
            IPHONE.format(os="17_4") + " Version/17.4 Mobile/15E148 Safari/604.1",
            Browser("Mobile Safari", 17, Engine.WEBKIT, (17, 4)),
        ),
        (
            IPHONE.format(os="16_1") + " CriOS/118.0 Mobile/15E148 Safari/604.1",
            Browser("Chrome iOS", 118, Engine.WEBKIT, (16, 1)),
        ),
        (
            IPHONE.format(os="17_0") + " FxiOS/130.0 Mobile/15E148 Safari/605.1.15",
            Browser("Firefox iOS", 130, Engine.WEBKIT, (17, 0)),
        ),
        (
            IPHONE.format(os="15_8") + " Mobile/15E148",
            Browser("iOS WebView", 15, Engine.WEBKIT, (15, 8)),
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko",
            Browser("IE", 11, Engine.LEGACY, None),
        ),
        (
            f"{chrome(70)} Edge/18.19041",
            Browser("Edge Legacy", 18, Engine.LEGACY, None),
        ),
        ("SomeKiosk/1.0", Browser("Other", None, Engine.UNKNOWN, None)),
    ],
)
def test_classify_names_brand_and_engine(user_agent: str, expected: Browser) -> None:
    assert classify(user_agent) == expected


@pytest.mark.parametrize(
    ("user_agent", "below"),
    [
        (chrome(110), True),
        (chrome(111), False),
        (f"{ANDROID} SamsungBrowser/21.0 Chrome/110.0.0.0 Mobile Safari/537.36", True),
        (firefox(127), True),
        (firefox(128), False),
        (safari("16.3"), True),
        (safari("16.4"), False),
        (safari("17"), False),
        (IPHONE.format(os="16_1") + " CriOS/130.0 Mobile/15E148 Safari/604.1", True),
        ("Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0)", True),
        ("SomeKiosk/1.0", False),
    ],
)
def test_below_baseline_follows_the_engine_floor(user_agent: str, below: bool) -> None:
    assert classify(user_agent).below_baseline is below


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "curl/8.5.0",
        "python-requests/2.32.3",
        f"{WINDOWS} HeadlessChrome/120.0.0.0 Safari/537.36",
        "-",
        "",
    ],
)
def test_automated_clients_are_recognised(user_agent: str) -> None:
    assert is_automated(user_agent)


def test_real_browsers_are_not_automated() -> None:
    assert not is_automated(chrome(126))
    assert not is_automated(safari("17.4"))


COMBINED = (
    '192.0.2.10 - - [15/Jan/2026:08:00:00 +0000] "GET /overview HTTP/1.1" 200 512 '
    f'"-" "{chrome(126)}"'
)


def test_parse_combined_line() -> None:
    request = parse_line(COMBINED)
    assert request is not None
    assert request.client == "192.0.2.10"
    assert request.epoch_seconds == 1768464000
    assert request.user_agent == chrome(126)


def test_parse_nginx_proxy_vhost_line_with_compose_prefix() -> None:
    line = (
        "nginx-1  | zz.example.org 192.0.2.11 - - [15/Jan/2026:10:00:00 +0200] "
        '"GET /api/query HTTP/2.0" 200 77 "https://zz.example.org/" '
        f'"{chrome(125)}" "172.18.0.5:5000"'
    )
    request = parse_line(line)
    assert request is not None
    assert request.client == "192.0.2.11"
    assert request.epoch_seconds == 1768464000
    assert request.user_agent == chrome(125)


@pytest.mark.parametrize(
    "line",
    [
        "",
        "2026/01/15 08:00:00 [error] 12#12: *1 connect() failed",
        COMBINED.replace("15/Jan/2026", "15/Foo/2026"),
    ],
)
def test_unparseable_lines_return_none(line: str) -> None:
    assert parse_line(line) is None
