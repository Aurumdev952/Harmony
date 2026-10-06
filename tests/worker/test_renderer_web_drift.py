"""WP-1h: what the web app and the renderer service must agree on.

The web app keeps its own copies of the renderer's limits, from when its image
ran Python 3.8 and could not import the renderer package. The 3.13 image can, so
the copies are due to go (backend request in WP-3b); until then this host-lane
test fails when the two drift apart. It is not under
tests/worker/renderer, which also runs inside the renderer image, where the web
app is not installed.
"""

import os
import re
from pathlib import Path

# Test-only placeholders read at import time by config modules.
os.environ.setdefault('DEFAULT_SECRET_KEY', 'tests-worker-placeholder-key')
os.environ.setdefault('DRUID_HOST', 'http://druid.invalid')
os.environ.setdefault('ZEN_ENV', 'harmony_demo')

# pylint: disable=wrong-import-position
from harmony.worker.renderer import server, spec  # noqa: E402
from harmony.worker.renderer.__main__ import settings_from_env  # noqa: E402
from web.server.routes.views import page_renderer  # noqa: E402

COMPOSE = Path(__file__).resolve().parents[2] / 'docker-compose.yaml'


def _compose_default_concurrency() -> int:
    found = re.search(
        r'RENDERER_CONCURRENCY=\$\{RENDERER_CONCURRENCY:-(\d+)\}', COMPOSE.read_text()
    )
    assert found, 'docker-compose.yaml no longer sets RENDERER_CONCURRENCY'
    return int(found.group(1))


def test_one_account_cannot_fill_the_renderer(monkeypatch):
    # With the cap at the renderer's concurrency, one account's exports left
    # every other account's renders, Overview thumbnails included, queueing
    # until their deadlines (review round 1, finding 4).
    monkeypatch.delenv('RENDERER_CONCURRENCY', raising=False)
    cap = page_renderer.MAX_RENDERS_IN_FLIGHT_PER_ACCOUNT

    assert 1 <= cap < settings_from_env().concurrency
    assert cap < _compose_default_concurrency()


def test_the_web_app_asks_only_for_what_the_renderer_accepts(monkeypatch):
    # The web app falls back to its defaults for an arg outside these, so a
    # copy that drifts wider sends requests the renderer refuses with a 400.
    monkeypatch.delenv('RENDERER_MAX_TIMEOUT_SECONDS', raising=False)
    monkeypatch.delenv('RENDERER_MAX_BYTES', raising=False)
    renderer = settings_from_env()

    assert page_renderer.WIDTHS == spec.WIDTHS
    assert page_renderer.HEIGHTS == spec.HEIGHTS
    assert page_renderer.PDF_PAGE_SIZES == spec.PDF_PAGE_SIZES
    assert page_renderer.CONTENT_TYPES == server.CONTENT_TYPES
    assert set(page_renderer.CONTENT_TYPES) == set(spec.FORMATS)
    assert page_renderer.DEFAULT_WIDTH in spec.WIDTHS
    assert page_renderer.DEFAULT_HEIGHT in spec.HEIGHTS
    assert page_renderer.RENDER_TIMEOUT_SECONDS <= renderer.max_timeout_seconds
    assert page_renderer.RENDER_MAX_BYTES == renderer.max_bytes


def test_the_renderer_answers_before_the_web_app_stops_reading(monkeypatch):
    # A render that overruns is killed at its deadline plus the clean-up grace
    # and answered 504; the web app must still be reading then, or it logs a
    # read timeout instead of the renderer's code. Its read timeout is also the
    # render token's and the slot's lifetime.
    monkeypatch.delenv('RENDERER_CLEANUP_GRACE_SECONDS', raising=False)
    latest_answer = (
        page_renderer.RENDER_TIMEOUT_SECONDS + settings_from_env().cleanup_grace_seconds
    )
    read_timeout = (
        page_renderer.RENDER_TIMEOUT_SECONDS + page_renderer.RESPONSE_MARGIN_SECONDS
    )

    assert latest_answer < read_timeout
