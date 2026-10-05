"""Offline checks that keep INVENTORY.md, the cases and the recordings in step."""

import json

from . import catalogue
from .cases import RELAY_PREFIX, Case, load_cases
from .inventory import RelayRow, load_inventory, load_relay_operations

CASES = load_cases()
ROWS = load_inventory()
RELAY_ROWS = load_relay_operations()


def test_inventory_has_no_duplicate_routes():
    assert catalogue.duplicate_routes(ROWS) == []


def test_every_case_names_an_inventory_row():
    assert catalogue.cases_without_a_row(CASES, ROWS) == []


def test_rows_are_recorded_with_cases_or_deferred_with_a_reason():
    assert catalogue.coverage_problems(CASES, ROWS) == []


def test_every_relay_operation_is_recorded_or_deferred():
    assert catalogue.relay_problems(CASES, RELAY_ROWS) == []


def test_captures_are_set_before_use():
    assert catalogue.capture_order_problems(CASES) == []


def test_every_case_has_a_matching_recording():
    assert catalogue.recording_problems(CASES) == []


def test_recordings_hold_no_values_that_look_like_secrets_or_pii():
    assert catalogue.leak_problems() == []


def test_relay_rows_with_empty_connections_say_so_and_why():
    assert catalogue.empty_connection_problems(CASES, RELAY_ROWS) == []


ARTIFACT = "web/client/x/__generated__/XQuery.graphql.js"
EMPTY = {"maxItems": 0, "type": "array"}
FILLED = {"items": {"type": "object"}, "type": "array"}


def _relay_fixture(tmp_path, coverage, edges):
    case = Case.from_json(
        {
            "id": "graphql.XQuery",
            "route": "POST /api/graphql",
            "body": {"query": RELAY_PREFIX + ARTIFACT, "variables": {}},
        }
    )
    connection = {"properties": {"edges": edges}, "type": "object"}
    recording = {"response_schema": {"properties": {"c": connection}}}
    (tmp_path / "graphql.XQuery.json").write_text(json.dumps(recording))
    return [case], [RelayRow("query", "XQuery", ARTIFACT, coverage, 1)]


def test_an_unannotated_empty_connection_is_a_problem(tmp_path):
    cases, rows = _relay_fixture(tmp_path, "recorded", EMPTY)
    assert catalogue.empty_connection_problems(cases, rows, tmp_path) == [
        "XQuery: every recording has an empty connection ($.c.edges); seed rows"
        " or mark it 'recorded (empty connection, <reason>)'"
    ]


def test_an_annotation_on_a_filled_connection_is_stale(tmp_path):
    cases, rows = _relay_fixture(tmp_path, "recorded (empty connection, F13)", FILLED)
    assert catalogue.empty_connection_problems(cases, rows, tmp_path) == [
        "XQuery: marked empty connection but a recording has items"
    ]


def test_an_annotated_empty_connection_passes(tmp_path):
    cases, rows = _relay_fixture(tmp_path, "recorded (empty connection, F13)", EMPTY)
    assert catalogue.empty_connection_problems(cases, rows, tmp_path) == []


def _route_case(case_id):
    return Case.from_json({"id": case_id, "route": "GET /api2/x"})


def _write(tmp_path, case_id, schema):
    (tmp_path / f"{case_id}.json").write_text(json.dumps({"response_schema": schema}))


def test_a_list_empty_in_every_recording_of_a_route_is_listed(tmp_path):
    cases = [_route_case("x.one"), _route_case("x.two")]
    _write(tmp_path, "x.one", {"properties": {"a": EMPTY, "b": EMPTY}})
    _write(tmp_path, "x.two", {"properties": {"a": EMPTY, "b": FILLED}})
    assert catalogue.always_empty_lists(cases, tmp_path) == {"GET /api2/x": ["$.a"]}


def test_nested_and_nullable_lists_are_scanned(tmp_path):
    item = {"properties": {"c": {"maxItems": 0, "type": ["array", "null"]}}}
    _write(tmp_path, "x.one", {"items": item, "type": "array"})
    assert catalogue.always_empty_lists([_route_case("x.one")], tmp_path) == {
        "GET /api2/x": ["$[].c"]
    }


def test_relay_lists_are_grouped_by_operation(tmp_path):
    cases, _ = _relay_fixture(tmp_path, "recorded", EMPTY)
    assert catalogue.always_empty_lists(cases, tmp_path) == {"XQuery": ["$.c.edges"]}
