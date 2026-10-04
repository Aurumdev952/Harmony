"""Offline checks that keep INVENTORY.md, the cases and the recordings in step."""

from . import catalogue
from .cases import load_cases
from .inventory import load_inventory, load_relay_operations

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
