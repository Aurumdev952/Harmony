'''`config.settings` no longer carries the urlbox-era render settings (WP-1h).

The renderer sidecar replaced urlbox.io and render tokens are minted for the
requesting user, so neither the urlbox API key nor the render-bot account is a
setting any more. The module runs in a fresh interpreter with both variables
set, so a leftover `getenv` would surface as an attribute.
'''

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REMOVED = ('URLBOX_API_KEY', 'RENDERBOT_EMAIL')


def test_settings_do_not_expose_urlbox_or_render_bot():
    env = {
        **os.environ,
        'PYTHONDONTWRITEBYTECODE': '1',
        'DEFAULT_SECRET_KEY': 'tests-core-placeholder-key',
        'DRUID_HOST': 'http://druid.invalid',
        'ZEN_ENV': 'harmony_demo',
        'URLBOX_API_KEY': 'leftover-key',
        'RENDERBOT_EMAIL': 'renderbot@example.invalid',
    }
    code = (
        'import json\n'
        'from config import settings\n'
        f'print(json.dumps([n for n in {REMOVED!r} if hasattr(settings, n)]))\n'
    )
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []
