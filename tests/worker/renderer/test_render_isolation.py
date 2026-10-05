"""WP-1h: each render runs in a child process, killed with everything it started
once it overruns its deadline plus the clean-up grace.

The targets are module-level so the spawned child can import them by name.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from harmony.worker.renderer.errors import PageFailed, RenderError, RenderTimeout
from harmony.worker.renderer.isolation import run_isolated
from harmony.worker.renderer.server import RendererSettings, RenderOutput
from harmony.worker.renderer.spec import RenderSpec, Viewport

TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6InRlc3QifQ.c2lnbmF0dXJl'
PID_FILE = 'RENDER_ISOLATION_TEST_PID_FILE'
ANSWER_AT = 'RENDER_ISOLATION_TEST_ANSWER_AT'


def _settings(**overrides: float) -> RendererSettings:
    values: dict = dict(
        allowed_origin='http://web:5000',
        port=0,
        max_timeout_seconds=30.0,
        max_bytes=1024,
        concurrency=1,
        max_page_height=2000,
        cleanup_grace_seconds=0.5,
    )
    values.update(overrides)
    return RendererSettings(**values)


def _spec(timeout_seconds: float = 5.0) -> RenderSpec:
    return RenderSpec(
        url='http://web:5000/dashboard/malaria?screenshot=1',
        token=TOKEN,
        format='png',
        viewport=Viewport(1280, 800),
        full_page=False,
        pdf_page_size='A4',
        pdf_landscape=False,
        timeout_seconds=timeout_seconds,
    )


def answers(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
    return RenderOutput(content=f'{os.getpid()}'.encode(), blocked_hosts=('x',))


def page_fails(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
    raise PageFailed('dashboard page answered 500')


def crashes(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
    raise RuntimeError(f'boom {spec.token}')


def dies(spec: RenderSpec, settings: RendererSettings) -> RenderOutput:
    os._exit(3)


def hangs_with_a_detached_helper(
    spec: RenderSpec, settings: RendererSettings
) -> RenderOutput:
    # As Playwright starts Chromium: in a session of its own, so killing the
    # child's process group would miss it.
    helper = subprocess.Popen(
        [sys.executable, '-c', 'import time; time.sleep(600)'],
        start_new_session=True,
    )
    Path(os.environ[PID_FILE]).write_text(str(helper.pid))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)


def _is_running(pid: int) -> bool:
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
    except OSError:
        # Gone: FileNotFoundError, or ProcessLookupError if it exited mid-read.
        return False
    return state != 'Z'


def test_the_answer_comes_back_from_a_child_process():
    output = run_isolated(answers, _spec(), _settings())

    assert output.blocked_hosts == ('x',)
    assert int(output.content) != os.getpid()


def test_a_render_error_in_the_child_is_raised():
    with pytest.raises(PageFailed, match='answered 500'):
        run_isolated(page_fails, _spec(), _settings())


def test_an_unexpected_error_is_reported_by_its_type_only():
    with pytest.raises(RenderError) as raised:
        run_isolated(crashes, _spec(), _settings())

    assert raised.value.status == 500
    assert str(raised.value) == 'RuntimeError'


def test_a_child_that_dies_without_answering_is_a_failure():
    with pytest.raises(RenderError) as raised:
        run_isolated(dies, _spec(), _settings())

    assert raised.value.status == 500


@pytest.mark.skipif(not Path('/proc/self/stat').exists(), reason='needs /proc')
def test_an_overrun_kills_the_child_and_everything_it_started(tmp_path, monkeypatch):
    pid_file = tmp_path / 'helper.pid'
    monkeypatch.setenv(PID_FILE, str(pid_file))
    started = time.monotonic()

    with pytest.raises(RenderTimeout):
        run_isolated(
            hangs_with_a_detached_helper,
            _spec(timeout_seconds=1.0),
            _settings(cleanup_grace_seconds=0.5),
        )

    assert time.monotonic() - started < 4
    helper = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while _is_running(helper) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert not _is_running(helper)
    finally:
        if _is_running(helper):
            with contextlib.suppress(ProcessLookupError):
                os.kill(helper, signal.SIGKILL)


def answers_late_and_lingers(
    spec: RenderSpec, settings: RendererSettings
) -> RenderOutput:
    # Answers just inside the limit, then cannot exit: interpreter shutdown
    # waits for this non-daemon thread.
    threading.Thread(target=time.sleep, args=(600,)).start()
    time.sleep(max(float(os.environ[ANSWER_AT]) - time.monotonic(), 0))
    return RenderOutput(content=b'late', blocked_hosts=())


def test_a_late_answer_still_frees_the_slot_by_the_deadline_plus_grace(monkeypatch):
    # Found in security re-check: waiting a further grace for the child to exit
    # after a late answer reached the watchdog's stuck threshold.
    started = time.monotonic()
    monkeypatch.setenv(ANSWER_AT, str(started + 3.6))

    output = run_isolated(
        answers_late_and_lingers,
        _spec(timeout_seconds=2.0),
        _settings(cleanup_grace_seconds=2.0),
    )

    assert output.content == b'late'
    # The limit is 4.0 s; waiting a further grace after the answer took 5.6 s.
    assert time.monotonic() - started < 5.0
