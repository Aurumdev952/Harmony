import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from .schema import diff, infer, merge

MARKER = "SENSITIVE"

shaped_strings = st.sampled_from(
    [
        "2024-01-01",
        "2024-01-01T10:00:00Z",
        "2024-01-01 10:00:00",
        "Mon, 01 Jan 2024 10:00:00 GMT",
        "someone@example.org",
        "/api2/dashboard/12",
        "123e4567-e89b-12d3-a456-426614174000",
    ]
)
leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=8),
    shaped_strings,
)
record_keys = st.sampled_from(
    ["id", "name", "$uri", "created", "items", "value", "isOfficial"]
)
data_keys = st.one_of(
    st.integers(0, 999).map(str),
    st.sampled_from(["a@b.org", "2024-01-01", "/api2/user/3"]),
)
json_values = st.recursive(
    leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(record_keys, children, max_size=4),
        st.dictionaries(data_keys, children, min_size=1, max_size=4),
    ),
    max_leaves=25,
)


def accepts(schema, value):
    return not list(Draft202012Validator(schema).iter_errors(value))


@given(json_values)
def test_inferred_schema_accepts_its_own_value(value):
    assert accepts(infer(value), value)


@given(json_values, json_values)
def test_merged_schema_accepts_both_values(a, b):
    merged = merge(infer(a), infer(b))
    assert accepts(merged, a)
    assert accepts(merged, b)


@given(json_values, json_values)
def test_merge_is_commutative(a, b):
    assert merge(infer(a), infer(b)) == merge(infer(b), infer(a))


@given(st.lists(json_values, min_size=1, max_size=5))
def test_array_shape_ignores_item_order_and_repeats(items):
    assert infer(items) == infer(list(reversed(items)))
    assert infer(items + items) == infer(items)


@settings(max_examples=300)
@given(json_values, json_values)
def test_diff_is_empty_exactly_when_shapes_are_equal(a, b):
    sa, sb = infer(a), infer(b)
    assert (diff(sa, sb) == []) == (sa == sb)


secret_text = st.text(min_size=1, max_size=6).map(lambda s: f"{MARKER}{s}")
secret_values = st.recursive(
    st.one_of(secret_text, secret_text.map(lambda s: f"{s}@example.org")),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(record_keys, children, max_size=3),
        st.dictionaries(
            secret_text.map(lambda s: f"{s}@example.org"),
            children,
            min_size=1,
            max_size=3,
        ),
        st.dictionaries(st.integers(0, 99).map(str), children, min_size=1, max_size=3),
    ),
    max_leaves=15,
)


@given(secret_values)
def test_schema_never_contains_values_or_data_keys(value):
    assert MARKER not in json.dumps(infer(value))


def test_record_lists_keys_and_marks_them_required():
    assert infer({"name": "x", "id": 1}) == {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
        "required": ["id", "name"],
    }


def test_keys_that_are_data_collapse_into_a_map():
    shape = infer(
        {"someone@example.org": {"admin": True}, "other@example.org": {"admin": False}}
    )
    assert shape == {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "properties": {"admin": {"type": "boolean"}},
            "required": ["admin"],
        },
    }


def test_keys_missing_from_some_list_items_are_optional():
    shape = infer([{"id": 1, "parent": 2}, {"id": 2}])
    assert shape["items"]["required"] == ["id"]
    assert set(shape["items"]["properties"]) == {"id", "parent"}


def test_nullable_field_records_both_types():
    assert infer([{"v": None}, {"v": 1.5}])["items"]["properties"]["v"] == {
        "type": ["null", "number"]
    }


@pytest.mark.parametrize(
    ("value", "fmt"),
    [
        ("Mon, 01 Jan 2024 10:00:00 GMT", "http-date"),
        ("2024-01-01T10:00:00.123+00:00", "date-time"),
        ("2024-01-01 10:00:00", "date-time-space"),
        ("/api2/dashboard/4", "api-uri"),
        ("hello", None),
    ],
)
def test_string_format_tags(value, fmt):
    assert infer(value).get("x-format") == fmt


def test_diff_explains_serialisation_and_key_drift():
    recorded = infer(
        {
            "created": "Mon, 01 Jan 2024 10:00:00 GMT",
            "$uri": "/api2/dashboard/1",
            "id": 1,
        }
    )
    replayed = infer(
        {"created": "2024-01-01T10:00:00Z", "uri": "/api/v3/dashboards/1", "id": "1"}
    )
    assert diff(recorded, replayed) == [
        "$: missing key '$uri'",
        "$: unexpected key 'uri'",
        "$.created: string format 'http-date' != 'date-time'",
        "$.id: type ['integer'] != ['string']",
    ]


def test_diff_reports_key_becoming_optional():
    always = infer([{"id": 1, "parent": 2}])
    sometimes = infer([{"id": 1, "parent": 2}, {"id": 2}])
    assert diff(always, sometimes) == [
        "$[].parent: always present in recording, not now"
    ]


def test_diff_reports_empty_array_turning_non_empty():
    assert diff(infer({"rows": []}), infer({"rows": [1]})) == [
        "$.rows: array is empty in recording, non-empty now"
    ]


def test_declared_map_paths_collapse_keys_the_heuristics_miss():
    response = {
        "totals": {"Kigali": {"cases": 1.5}, "Huye": {"cases": 2.0}},
        "dates": ["2024-01-01"],
    }
    shape = infer(response, frozenset({"$.totals"}))
    assert shape["properties"]["totals"] == {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "properties": {"cases": {"type": "number"}},
            "required": ["cases"],
        },
    }
    assert "Kigali" not in json.dumps(shape)


def test_map_paths_reach_into_arrays_and_maps():
    shape = infer(
        {"rows": [{"byState": {"Kigali": 1}}]}, frozenset({"$.rows[].byState"})
    )
    assert shape["properties"]["rows"]["items"]["properties"]["byState"] == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }


def test_a_declared_map_that_is_empty_stays_a_map():
    maps = frozenset({"$.totals"})
    empty, full = infer({"totals": {}}, maps), infer({"totals": {"Kigali": 1}}, maps)
    assert diff(empty, full) == ["$.totals: map is empty in recording, non-empty now"]
    assert merge(empty, full) == full
    assert diff(full, infer({"totals": {"Huye": 2}}, maps)) == []
