"""WP-1h end-to-end check on the disposable stack (WP-2c stack + renderer + tap).

Never prints a password or a token.
"""
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = 'http://127.0.0.1:58761'
PROJECT = 'wp1h-e2e'
STACK = '/tmp/wp1h-e2e/tests/contract/stack'  # noqa: S108
SLUG = 'wp1h-render-check-3'
OUT = Path('/tmp/wp1h-e2e-out')  # noqa: S108
TAP = Path('/tmp/wp1h-tap/calls.jsonl')  # noqa: S108
OUTSIDER = 'outsider@harmony.invalid'


def secrets_file() -> Path:
    base = os.environ.get('XDG_RUNTIME_DIR') or str(
        Path.home() / '.local/state/harmony-contract'
    )
    return Path(base) / f'{PROJECT}.env'


def admin_headers() -> dict:
    values = dict(
        line.split('=', 1) for line in secrets_file().read_text().split() if '=' in line
    )
    return {
        'X-Username': 'contract-admin@harmony.invalid',
        'X-Password': values['CONTRACT_PASSWORD'],
    }


# Output of wp1h_spec.py run inside the web container.
SPEC = json.loads(Path('/tmp/wp1h-spec.json').read_text())  # noqa: S108


def png_size(data):
    return struct.unpack('>II', data[16:24])


def jpeg_size(data):
    i = 2
    while i < len(data):
        marker, length = data[i + 1], struct.unpack('>H', data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack('>HH', data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def pdf_info(data):
    pages = len(re.findall(rb'/Type\s*/Page[^s]', data))
    box = re.search(
        rb'/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)', data
    )
    return pages, box.group(3).decode() + 'x' + box.group(4).decode() if box else None


def tap_calls():
    if not TAP.exists():
        return []
    return [json.loads(line) for line in TAP.read_text().splitlines() if line]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    report = {}
    admin = admin_headers()

    created = requests.post(
        f'{BASE}/api2/dashboard',
        json={'slug': SLUG, 'specification': SPEC},
        headers=admin,
        timeout=30,
    )
    report['create_dashboard'] = created.status_code

    for name, route, fmt in [
        ('pdf', f'/dashboard/{SLUG}/pdf', 'pdf'),
        ('jpeg', f'/dashboard/{SLUG}/jpeg', 'jpeg'),
        ('png_thumbnail', f'/dashboard/{SLUG}/png/thumbnail', 'png'),
    ]:
        started = time.monotonic()
        response = requests.get(f'{BASE}{route}', headers=admin, timeout=200)
        entry = {
            'status': response.status_code,
            'content_type': response.headers.get('Content-Type'),
            'bytes': len(response.content),
            'seconds': round(time.monotonic() - started, 2),
        }
        if response.status_code == 200:
            (OUT / f'{name}.{fmt}').write_bytes(response.content)
            if fmt == 'png':
                entry['pixels'] = png_size(response.content)
            elif fmt == 'jpeg':
                entry['pixels'] = jpeg_size(response.content)
            else:
                entry['pdf_pages'], entry['pdf_mediabox'] = pdf_info(response.content)
        report[name] = entry

    calls = tap_calls()
    report['renderer_calls'] = [
        {
            'url': c['url'],
            'format': c['format'],
            'timeout_seconds': c['timeout_seconds'],
        }
        for c in calls
    ]
    if calls:
        token = calls[-1]['token']
        replay = requests.get(
            f'{BASE}/dashboard/{SLUG}',
            headers={'Cookie': f'accessKey={token}'},
            allow_redirects=False,
            timeout=30,
        )
        api_replay = requests.get(
            f'{BASE}/api2/dashboard',
            headers={'Cookie': f'accessKey={token}'},
            allow_redirects=False,
            timeout=30,
        )
        report['token_reuse_after_render'] = {
            'dashboard_page': [replay.status_code, replay.headers.get('Location')],
            'api2_dashboard': api_replay.status_code,
        }

    password = secrets.token_hex(16)
    subprocess.run(
        [
            'docker',
            'compose',
            '-p',
            PROJECT,
            '-f',
            f'{STACK}/compose.yaml',
            '-f',
            f'{STACK}/compose.renderer.yaml',
            '-f',
            f'{STACK}/compose.redis-auth.yaml',
            '-f',
            f'{STACK}/compose.hasura-secret.yaml',
            'exec',
            '-T',
            'web',
            'python',
            'scripts/create_user.py',
            '--username',
            OUTSIDER,
            '--password',
            password,
            '--first_name',
            'Out',
            '--last_name',
            'Sider',
            '--overwrite',
        ],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            **{
                k: 'unused'
                for k in (
                    'CONTRACT_WEB_IMAGE',
                    'CONTRACT_PASSWORD',
                    'POSTGRES_PASSWORD',
                    'REDIS_PASSWORD',
                    'HASURA_ADMIN_SECRET',
                    'DEFAULT_SECRET_KEY',
                    'JWT_SECRET_KEY',
                    'CONTRACT_USERNAME',
                    'CONTRACT_WEB_PORT',
                )
            },
            'CONTRACT_PROJECT': PROJECT,
        },
    )
    before = len(tap_calls())
    outsider = requests.get(
        f'{BASE}/dashboard/{SLUG}/pdf',
        headers={'X-Username': OUTSIDER, 'X-Password': password},
        timeout=60,
    )
    report['outsider_pdf'] = {
        'status': outsider.status_code,
        'renderer_calls_made': len(tap_calls()) - before,
    }
    anonymous = requests.get(f'{BASE}/dashboard/{SLUG}/pdf', timeout=60)
    report['anonymous_pdf'] = {
        'status': anonymous.status_code,
        'renderer_calls_made': len(tap_calls()) - before,
    }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
