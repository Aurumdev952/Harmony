'''Backend-2 evidence for WP-2g: one request id across the response header, the view's
JSON line, `g.request_id`, and a task published from the request and run by a worker.

Run on the 3.8 web env from the repo root; output in backend2_wiring_live.jsonl:
    PYTHONPATH=. ZEN_ENV=harmony_demo DRUID_HOST=http://druid.invalid \
    DEFAULT_SECRET_KEY=<32+ chars> JWT_SECRET_KEY=<32+ chars> \
    SQLALCHEMY_DATABASE_URI=postgresql://zen@db.invalid/zen \
    LOG_FORMAT=json LOG_STREAM=stdout LOG_LEVEL=WARNING \
    python -W ignore docs/modernisation/work/WP-2g-evidence/backend2_wiring_live.py
The database is never connected to. Outside gunicorn, create_app skips Flask-User
setup and register_for_signals, so the script adds a LoginManager and connects
initialize_request_logger the same way.
'''

import json

from celery import Celery
from celery.contrib.testing.worker import start_worker
from flask import g, request_started
from flask_login import LoginManager

from log import LOG
from web.server.app import create_app
from web.server.security.signal_handlers import initialize_request_logger
from web.server.workers import create_celery

app = create_app(skip_db_check=True)
LoginManager(app)
request_started.connect(initialize_request_logger, app)
create_celery({})

worker_app = Celery('wp2g-evidence', broker='memory://', backend='cache+memory://')


def log_in_task():
    LOG.warning('in evidence task')
    return 'done'


evidence_task = worker_app.task(name='wp2g.evidence_task')(log_in_task)


@app.route('/wp2g-view')
def view():
    g.request_logger.warning('wp2g view line')
    evidence_task.delay().get(timeout=20)
    return str(g.request_id)


with start_worker(worker_app, pool='solo', perform_ping_check=False):
    response = app.test_client().get('/wp2g-view')
print(
    json.dumps(
        {
            'probe': 'response',
            'status': response.status_code,
            'X-Request-ID': response.headers.get('X-Request-ID'),
            'g.request_id': response.get_data(as_text=True),
        }
    )
)
