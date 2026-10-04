"""Replays every recorded case against CONTRACT_BASE_URL and compares shapes.

Cases run in recording order and share captures, so they must run in one
process and in order (no pytest-xdist, no -k that drops a producer case).
"""

import json

import pytest

from .cases import compare, load_cases, recording_path

pytestmark = pytest.mark.stack


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c.id)
def test_replay_matches_recording(case, contract_runner):
    from .runner import SkipCase

    recorded = json.loads(recording_path(case.id).read_text())
    try:
        observed = contract_runner.run(case)
    except SkipCase as exc:
        pytest.fail(str(exc))
    assert compare(recorded, observed) == []
