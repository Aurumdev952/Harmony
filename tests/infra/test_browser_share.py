import gzip
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prod" / "browser_share"))

from browser_share import (  # noqa: E402
    Browser,
    BrowserShare,
    DeploymentReport,
    Engine,
    Gate,
    build_report,
    classify,
    count_sessions,
    is_automated,
    main,
    parse_line,
    phase_7_gate,
    read_lines,
)

FIXTURE = Path(__file__).parent / "testdata" / "zz" / "access_log.txt"

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


def log_line(client: str, user_agent: str, when: str = "08:00:00") -> str:
    return (
        f'{client} - - [15/Jan/2026:{when} +0000] "GET /overview HTTP/1.1" 200 512 '
        f'"-" "{user_agent}"'
    )


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
            f"{ANDROID} Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.4.0.1306"
            " Mobile Safari/537.36",
            Browser("UC Browser", 13, Engine.BLINK, (78, 0)),
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
            IPHONE.format(os="18_6") + " Version/26.0 Mobile/15E148 Safari/604.1",
            Browser("Mobile Safari", 26, Engine.WEBKIT, (26, 0)),
        ),
        (
            IPHONE.format(os="16_1") + " CriOS/118.0 Mobile/15E148 Safari/604.1",
            Browser("Chrome iOS", 118, Engine.WEBKIT, (16, 1)),
        ),
        (
            IPHONE.format(os="16_5")
            + " Version/16.0 EdgiOS/114.0.1823.79 Mobile/15E148 Safari/605.1.15",
            Browser("Edge iOS", 114, Engine.WEBKIT, (16, 5)),
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
        (
            IPHONE.format(os="16_4") + " Version/16.0 EdgiOS/114.0 Mobile/15E148",
            False,
        ),
        (IPHONE.format(os="18_6") + " Version/26.0 Mobile/15E148 Safari/604.1", False),
        ("Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0)", True),
        ("SomeKiosk/1.0", False),
    ],
)
def test_below_baseline_follows_the_engine_floor(user_agent: str, below: bool) -> None:
    assert classify(user_agent).below_baseline is below


@pytest.mark.parametrize(
    "user_agent",
    [
        f"{WINDOWS} Chrome/{'9' * 5000}.0 Safari/537.36",
        IPHONE.format(os="1" * 5000 + "_0") + f" Version/{'2' * 5000}.0",
        f"Mozilla/5.0 (Windows NT 10.0; rv:1.0) Gecko/20100101 Firefox/{'7' * 5000}",
    ],
)
def test_huge_version_numbers_do_not_crash(user_agent: str) -> None:
    assert classify(user_agent).engine_version is None
    report = build_report("zz", [log_line("192.0.2.10", user_agent)])
    assert report.sessions == 1


@pytest.mark.parametrize(
    "user_agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
        "Mozilla/5.0 (compatible; bot)",
        "curl/8.5.0",
        "python-requests/2.32.3",
        f"{WINDOWS} HeadlessChrome/120.0.0.0 Safari/537.36",
        "-",
        "",
    ],
)
def test_automated_clients_are_recognised(user_agent: str) -> None:
    assert is_automated(user_agent)


@pytest.mark.parametrize(
    "user_agent",
    [
        chrome(126),
        safari("17.4"),
        "Mozilla/5.0 (Linux; Android 11; CUBOT X30) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ],
)
def test_real_browsers_are_not_automated(user_agent: str) -> None:
    assert not is_automated(user_agent)


COMBINED = log_line("192.0.2.10", chrome(126))


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
        '{"time": "2026-01-15T08:00:00Z", "ua": "Chrome/126"}',
    ],
)
def test_unparseable_lines_return_none(line: str) -> None:
    assert parse_line(line) is None


def test_long_junk_lines_are_rejected_quickly() -> None:
    junk = [
        "a" * 50_000,
        "x " * 25_000,
        "x - - " * 8_500,
        "192.0.2.1 - - [" + "a" * 50_000,
        '192.0.2.1 - - [15/Jan/2026:08:00:00 +0000] "' + "a" * 50_000,
        '"' + "\\a" * 25_000,
        "nginx-1 | " * 5_000,
    ]
    started = time.perf_counter()
    assert [parse_line(line) for line in junk] == [None] * len(junk)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("below", "total", "gate"),
    [
        (0, 0, Gate.NOT_EVALUATED),
        (0, 1, Gate.WITHIN),
        (5, 100, Gate.WITHIN),
        (500, 10_000, Gate.WITHIN),
        (501, 10_000, Gate.ABOVE),
        (504, 10_000, Gate.ABOVE),
        (1, 1, Gate.ABOVE),
    ],
)
def test_gate_compares_raw_counts(below: int, total: int, gate: Gate) -> None:
    assert phase_7_gate(below, total) is gate


def sessions_with_below(below: int, total: int) -> list[str]:
    return [
        log_line(f"2001:db8::{i:x}", chrome(110 if i < below else 126))
        for i in range(total)
    ]


def test_gate_is_not_fooled_by_rounding() -> None:
    report = build_report("zz", sessions_with_below(504, 10_000))
    assert report.below_baseline_pct == 5.0
    assert report.phase_7_gate is Gate.ABOVE


def test_gate_at_exactly_five_percent_passes() -> None:
    report = build_report("zz", sessions_with_below(500, 10_000))
    assert report.phase_7_gate is Gate.WITHIN


EXPECTED_SHARES = [
    BrowserShare("Chrome", 126, 20.0),
    BrowserShare("Chrome", 109, 10.0),
    BrowserShare("Chrome iOS", 118, 10.0),
    BrowserShare("Edge", 125, 10.0),
    BrowserShare("Firefox", 130, 10.0),
    BrowserShare("Firefox", 115, 10.0),
    BrowserShare("Mobile Safari", 17, 10.0),
    BrowserShare("Other", None, 10.0),
    BrowserShare("Safari", 16, 10.0),
]


def assert_fixture_report(report: DeploymentReport) -> None:
    assert report.deployment == "zz"
    assert report.sessions == 10
    assert list(report.browsers) == EXPECTED_SHARES
    assert report.below_baseline_sessions == 4
    assert report.below_baseline_pct == 40.0
    assert report.unknown_engine_pct == 10.0
    assert report.automated_requests == 3
    assert report.unparsed_lines == 1
    assert report.phase_7_gate is Gate.ABOVE


@pytest.mark.parametrize(
    ("times", "sessions"),
    [
        ([], 0),
        ([0], 1),
        ([0, 1800], 1),
        ([0, 1801], 2),
        ([5000, 0, 1000, 2000], 2),
    ],
)
def test_sessions_split_on_gaps_over_thirty_minutes(
    times: list[int], sessions: int
) -> None:
    assert count_sessions(times) == sessions


def test_report_from_fixture() -> None:
    assert_fixture_report(build_report("zz", FIXTURE.read_text().splitlines()))


def test_rotated_gzipped_files_give_the_same_report(tmp_path: Path) -> None:
    lines = FIXTURE.read_bytes().splitlines(keepends=True)
    current = tmp_path / "access.log"
    rotated = tmp_path / "access.log.1.gz"
    current.write_bytes(b"".join(lines[:6]))
    rotated.write_bytes(gzip.compress(b"".join(lines[6:])))

    report = build_report(
        "zz", (line for path in (rotated, current) for line in read_lines(str(path)))
    )
    assert_fixture_report(report)


@pytest.mark.parametrize(
    "lines",
    [
        [],
        ["2026/01/15 08:00:00 [error] 12#12: *1 connect() failed"],
        [log_line("198.51.100.99", "Mozilla/5.0 (compatible; Googlebot/2.1)")],
        ['{"time": "2026-01-15T08:00:00Z", "ua": "Chrome/126"}'],
    ],
)
def test_no_sessions_leaves_the_gate_not_evaluated(lines: list[str]) -> None:
    report = build_report("zz", lines)
    assert report.sessions == 0
    assert report.phase_7_gate is Gate.NOT_EVALUATED


def test_cli_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--deployment", "zz", "--json", str(FIXTURE)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["deployment"] == "zz"
    assert printed["browsers"][0] == {
        "family": "Chrome",
        "major": 126,
        "share_pct": 20.0,
    }
    assert printed["below_baseline_pct"] == 40.0
    assert printed["phase_7_gate"] == "above"


def test_cli_text_names_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--deployment", "qq", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Deployment qq: 10 sessions;")
    assert "4 of 10 sessions, 40.0% (above the 5% phase 7 gate;" in out


def test_cli_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stdin = io.TextIOWrapper(io.BufferedReader(io.BytesIO(FIXTURE.read_bytes())))
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["--deployment", "zz", "--json", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["sessions"] == 10


@pytest.mark.parametrize("as_json", [False, True])
def test_cli_exits_non_zero_without_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    empty = tmp_path / "access.log"
    empty.write_text("")
    argv = ["--deployment", "zz", *(["--json"] if as_json else []), str(empty)]
    assert main(argv) == 1
    out = capsys.readouterr().out
    if as_json:
        assert json.loads(out)["phase_7_gate"] == "not evaluated"
    else:
        assert "Phase 7 gate not evaluated" in out


def test_cli_never_prints_client_addresses(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--deployment", "zz", str(FIXTURE)])
    main(["--deployment", "zz", "--json", str(FIXTURE)])
    out = capsys.readouterr().out
    for address in ("192.0.2.", "198.51.100.", "203.0.113.", "2001:db8", "127.0.0.1"):
        assert address not in out


@pytest.mark.parametrize("argv", [[str(FIXTURE)], ["-"]])
def test_cli_requires_deployment(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(argv)
    assert exited.value.code == 2
