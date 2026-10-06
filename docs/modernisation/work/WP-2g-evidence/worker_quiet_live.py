'''Start a Celery 5.4 worker for a few seconds with and without the global `-q`,
on an in-memory broker, with logging configured by `log` as in the worker image,
and report every stdout line that is not JSON.

    uv run python docs/modernisation/work/WP-2g-evidence/worker_quiet_live.py
'''

import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[4]
APP = '''
import log  # configures logging, as web.background_worker does first
from celery import Celery
from log.celery_signals import connect_celery_logging

celery = Celery('wp2g_quiet', broker='memory://', backend='cache+memory://')
connect_celery_logging()


@celery.task
def ping():
    return 'pong'
'''


def run(quiet: bool) -> str:
    with tempfile.TemporaryDirectory() as scratch:
        pathlib.Path(scratch, 'wp2g_quiet_app.py').write_text(APP)
        env = dict(
            os.environ,
            PYTHONPATH=f'{scratch}{os.pathsep}{ROOT}',
            LOG_FORMAT='json',
            LOG_STREAM='stdout',
            ZEN_ENV='rw',
        )
        command = ['celery', *(['-q'] if quiet else []), '-A', 'wp2g_quiet_app']
        command += ['worker', '--pool=solo']
        with subprocess.Popen(
            command, env=env, cwd=scratch, stdout=subprocess.PIPE, text=True
        ) as worker:
            time.sleep(6)
            worker.send_signal(signal.SIGTERM)
            stdout, _ = worker.communicate(timeout=30)
    return stdout


def plain_lines(stdout: str) -> list:
    plain = []
    for line in stdout.splitlines():
        try:
            json.loads(line)
        except ValueError:
            if line.strip():
                plain.append(line)
    return plain


# Celery's SIGTERM handler prints this to sys.__stdout__ whatever the options
# (celery/apps/worker.py, _shutdown_handler). It is the one line `-q` cannot stop.
SHUTDOWN = 'worker: Warm shutdown (MainProcess)'

failed = False
for quiet in (False, True):
    stdout = run(quiet)
    plain = plain_lines(stdout)
    json_lines = len(stdout.splitlines()) - len(plain)
    before_stop = [line for line in plain if line != SHUTDOWN]
    label = 'celery -q' if quiet else 'celery'
    print(
        f'{label}: {json_lines} JSON lines; plain-text lines: {len(before_stop)} '
        f'while running, {len(plain) - len(before_stop)} on SIGTERM'
    )
    for line in before_stop[:5]:
        print(f'    {line}')
    if quiet and before_stop:
        failed = True
sys.exit(1 if failed else 0)
