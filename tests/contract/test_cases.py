import os

import pytest

from .cases import (
    Case,
    capture_value,
    compare,
    describe_set_cookie,
    observe,
    pin_value,
    substitute,
)
from .runner import Credentials

JSON = {"Content-Type": "application/json"}


def make_case(**overrides):
    raw = {"id": "x", "route": "GET /api2/thing"}
    raw.update(overrides)
    return Case.from_json(raw)


def test_substitute_keeps_the_type_of_a_whole_placeholder():
    captures = {"dash_id": 7, "dash": "/api2/dashboard/7"}
    assert substitute(
        {"dashboardId": "{dash_id}", "path": "{dash}/favorite"}, captures
    ) == {
        "dashboardId": 7,
        "path": "/api2/dashboard/7/favorite",
    }


def test_substitute_reads_the_environment(monkeypatch):
    monkeypatch.setenv("CONTRACT_SAMPLE", "value")
    assert substitute("{env:CONTRACT_SAMPLE}", {}) == "value"


def test_substitute_names_the_missing_capture():
    with pytest.raises(LookupError, match="'dash'"):
        substitute("{dash}", {})


def test_capture_takes_a_pointer_or_the_id_at_the_end_of_a_uri():
    doc = [{"$uri": "/api2/dashboard/12"}]
    assert capture_value(doc, "/0/$uri") == "/api2/dashboard/12"
    assert capture_value(doc, "/0/$uri#id") == 12
    node = {"id": "WzEsICJwdWJsaWMiLCAic2VsZl9zZXJ2ZV9zb3VyY2UiLCA0Ml0="}
    assert capture_value(node, "/id#relay") == 42


@pytest.mark.parametrize(
    ("doc", "spec"),
    [
        ({"$uri": "/api2/user/someone@example.org"}, "/$uri#id"),
        ({"id": "someone@example.org"}, "/id#relay"),
    ],
)
def test_a_failed_capture_transform_does_not_echo_the_value(doc, spec):
    with pytest.raises(ValueError) as caught:
        capture_value(doc, spec)
    assert "someone" not in str(caught.value)


def test_misspelt_case_keys_are_refused():
    with pytest.raises(ValueError, match="pins"):
        make_case(pins=["/id"])


def test_pins_that_name_secrets_are_refused():
    with pytest.raises(ValueError, match="refusing"):
        make_case(pin=["/access_token"])


def test_pinned_values_that_look_like_pii_are_refused():
    case = make_case(pin=["/owner"])
    with pytest.raises(ValueError, match="email"):
        observe(case, 200, JSON, b'{"owner": "a@b.org"}', recording=True)


def test_each_tokens_pin_the_sorted_set_of_values():
    users = [{"status": "pending"}, {"status": "active"}, {"status": "active"}]
    assert pin_value(users, "/[]/status") == ["active", "pending"]
    assert pin_value({"a": {"k": "X"}, "b": {"k": "Y"}}, "/{*}/k") == ["X", "Y"]
    assert pin_value({"v": 1}, "/v") == 1


def test_an_enum_value_changing_case_is_a_diff():
    case = make_case(pin=["/[]/resourceType"])
    recorded = observe(case, 200, JSON, b'[{"resourceType": "DASHBOARD"}]')
    replayed = observe(case, 200, JSON, b'[{"resourceType": "dashboard"}]')
    assert compare(recorded, replayed) == [
        "pinned /[]/resourceType: ['DASHBOARD'] != ['dashboard']"
    ]


def test_a_dropped_pinned_field_is_reported_not_raised():
    case = make_case(pin=["/version"])
    recorded = observe(case, 200, JSON, b'{"version": "2020-07-20"}')
    replayed = observe(case, 200, JSON, b"{}")
    assert compare(recorded, replayed) == [
        "$: missing key 'version'",
        "pinned /version: '2020-07-20' recorded, missing now",
    ]


def test_capture_errors_are_reported_after_the_shape_diff():
    case = make_case()
    recorded = observe(case, 200, JSON, b'{"$uri": "/api2/x/1"}')
    replayed = {
        **observe(case, 200, JSON, b'{"uri": "/api/v3/x/1"}'),
        "capture_errors": ["x from /$uri: KeyError"],
    }
    assert compare(recorded, replayed) == [
        "$: missing key '$uri'",
        "$: unexpected key 'uri'",
        "capture x from /$uri: KeyError",
    ]


def test_json_sent_as_text_html_still_records_its_shape():
    observation = observe(
        make_case(), 200, {"Content-Type": "text/html; charset=utf-8"}, b'{"rows": [1]}'
    )
    assert observation["content_type"] == "text/html"
    assert observation["response_schema"]["properties"]["rows"]["items"] == {
        "type": "integer"
    }


def test_compare_reports_status_content_type_and_shape():
    case = make_case()
    recorded = observe(case, 200, JSON, b'{"id": 1}')
    replayed = observe(case, 201, JSON, b'{"id": "1"}')
    assert compare(recorded, replayed) == [
        "status 200 != 201",
        "$.id: type ['integer'] != ['string']",
    ]


def test_credentials_never_print_the_password():
    assert "hunter2" not in repr(Credentials("someone", "hunter2"))


def test_credentials_file_must_be_private(tmp_path, monkeypatch):
    secrets = tmp_path / "contract.env"
    secrets.write_text("CONTRACT_PASSWORD=abc\n")
    os.chmod(secrets, 0o644)
    monkeypatch.setenv("CONTRACT_USERNAME", "someone")
    # setenv first so monkeypatch restores whatever from_env() exports.
    monkeypatch.setenv("CONTRACT_PASSWORD", "placeholder")
    monkeypatch.delenv("CONTRACT_PASSWORD")
    monkeypatch.setenv("CONTRACT_CREDENTIALS_FILE", str(secrets))
    with pytest.raises(PermissionError):
        Credentials.from_env()
    os.chmod(secrets, 0o600)
    assert Credentials.from_env().password == "abc"


@pytest.mark.parametrize(
    ("header", "described"),
    [
        (
            "accessKey=eyJhbGciOi.x.y; HttpOnly; Path=/",
            "accessKey; session; httponly; path=/",
        ),
        (
            "accessKey=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Path=/",
            "accessKey; cleared; httponly; path=/",
        ),
        (
            "session=abc; Max-Age=0; Secure; SameSite=Lax",
            "session; cleared; secure; samesite=lax",
        ),
        (
            "remember=abc; Expires=Wed, 01 Jan 2031 00:00:00 GMT; SameSite=STRICT",
            "remember; persistent; samesite=strict",
        ),
        ("k=v; Max-Age=60; Domain=example.org", "k; persistent; domain=example.org"),
    ],
)
def test_set_cookie_is_described_without_its_value(header, described):
    assert describe_set_cookie(header) == described


def test_cookie_changes_are_reported_only_for_cases_that_ask():
    case = make_case(cookies=True)
    cleared = observe(case, 200, {}, b"", ("accessKey=; Max-Age=0",))
    untouched = observe(case, 200, {}, b"", ())
    assert compare(cleared, untouched) == ["cookies ['accessKey; cleared'] != []"]
    assert "cookies" not in observe(
        make_case(), 200, {}, b"", ("accessKey=; Max-Age=0",)
    )


def test_a_replay_reports_an_unsafe_pinned_value_without_echoing_it():
    case = make_case(pin=["/owner"])
    recorded = observe(case, 200, JSON, b'{"owner": "team-a"}', recording=True)
    replayed = observe(case, 200, JSON, b'{"owner": "someone@example.org"}')
    problems = compare(recorded, replayed)
    assert problems == [
        "$.owner: string format None != 'email'",
        "pinned /owner: 'team-a' != '<not shown: a value looks like email>'",
    ]
    assert "someone" not in " ".join(problems)
