"""util.unix.BackgroundProcess error paths.

Run with: uv run pytest tests/core/test_unix.py
"""

import pytest

from util.unix import BackgroundProcess


class _FailingWait:
    def __init__(self, error):
        self._error = error

    def wait(self):
        raise self._error

    def poll(self):
        return 0


def test_wait_propagates_an_error_from_the_process_unchanged():
    background = BackgroundProcess('true')
    background.process.wait()
    error = OSError('wait failed')
    background.process = _FailingWait(error)

    with pytest.raises(OSError) as raised:
        background.wait()

    assert raised.value is error
