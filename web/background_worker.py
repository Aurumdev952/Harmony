import traceback

from celery.signals import task_failure, task_internal_error

from config import settings
from log import LOG
from web.server.configuration.flask import require_jwt_secret_key
from web.server.workers import create_celery

# Pool children build the Flask app in worker_process_init, where Celery logs a
# RuntimeError and carries on. Checking here makes `celery -A` exit before the pool.
require_jwt_secret_key(settings.DEFAULT_SECRET_KEY)

celery = create_celery()


@task_failure.connect
def handle_task_failure(**kwargs):
    task = kwargs.get('sender')
    error = traceback.format_exc()
    LOG.error(f'Task {task.name} failed with error: {error}')


@task_internal_error.connect
def handle_task_internal_error(**kwargs):
    task = kwargs.get('sender')
    error = traceback.format_exc()
    LOG.error(f'Task {task} failed with error: {error}')
