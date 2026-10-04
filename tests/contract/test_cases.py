import pytest

from .cases import Case, capture_value, compare, observe, substitute
from .runner import Credentials


def make_case(**overrides):
    raw = {"id": "x", "route": "GET /api2/thing"}
    raw.update(overrides)
    return Case.from_json(raw)


def test_substitute_keeps_the_type_of_a_whole_placeholder():
    assert substitute(
        {"dashboardId": "{dash_id}", "path": "{dash}/favorite"}, {"dash_id": 7, "dash": "/api2/dashboard/7"}
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


def test_status_only_cases_must_say_why():
    with pytest.raises(ValueError, match="note"):
        make_case(compare="status")


def test_pins_that_name_secrets_are_refused():
    with pytest.raises(ValueError, match="refusing"):
        make_case(pin=["/access_token"])


def test_pinned_values_that_look_like_pii_are_refused():
    case = make_case(pin=["/owner"])
    with pytest.raises(ValueError, match="email"):
        observe(case, None, 200, {"Content-Type": "application/json"}, b'{"owner": "a@b.org"}')


def test_json_sent_as_text_html_still_records_its_shape():
    observation = observe(make_case(), None, 200, {"Content-Type": "text/html; charset=utf-8"}, b'{"rows": [1]}')
    assert observation["content_type"] == "text/html"
    assert observation["response_schema"]["properties"]["rows"]["items"] == {"type": "integer"}


def test_compare_reports_status_content_type_and_shape():
    case = make_case()
    recorded = observe(case, None, 200, {"Content-Type": "application/json"}, b'{"id": 1}')
    replayed = observe(case, None, 201, {"Content-Type": "application/json"}, b'{"id": "1"}')
    assert compare(case, recorded, replayed) == ["status 200 != 201", "$.id: type ['integer'] != ['string']"]


def test_credentials_never_print_the_password():
    assert "hunter2" not in repr(Credentials("someone", "hunter2"))
