import os
import secrets
import socket
import sys
from pathlib import Path
from pylib.base.flags import Flags

# NOTE: Need to import our dev reloader since registration is handled in that
# file.
# pylint: disable=unused-import
import web.dev_reloader

from config import VALID_MODULES
from web.server.app import create_app
from web.server.configuration.instance import load_instance_configuration_from_file
from web.server.configuration.flask import FlaskConfiguration
from util.flask import build_flask_config


def start_postgres():
    '''Start postgres server on dev machine if it is not running already.'''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        port_in_use = s.connect_ex(('localhost', 5432)) == 0
        if not port_in_use:
            os.system('scripts/db/postgres/dev/start_postgres.sh')


def ensure_dev_hasura_admin_secret():
    '''Give local Hasura a random admin secret that survives restarts, unless the
    developer set HASURA_ADMIN_SECRET themselves.'''
    if os.environ.get('HASURA_ADMIN_SECRET'):
        return
    secret_path = Path.home() / '.config' / 'harmony' / 'hasura_admin_secret'
    if not secret_path.exists():
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as secret_file:
            secret_file.write(secrets.token_urlsafe(32))
    if secret_path.stat().st_mode & 0o077:
        raise PermissionError(
            f'{secret_path} is readable by other users. Run `chmod 600 {secret_path}`, '
            'or delete it so a new secret is generated.'
        )
    os.environ['HASURA_ADMIN_SECRET'] = secret_path.read_text().strip()


def main():
    Flags.PARSER.add_argument(
        '--db_name',
        type=str,
        required=False,
        help='The name of the database in the Postgres server to connect to',
    )
    Flags.PARSER.add_argument(
        '--db_uri',
        type=str,
        required=False,
        help='The specific Postgres URI connection string to use for connecting to the '
        'database. This should rarely be used.',
    )
    Flags.PARSER.add_argument(
        '--port',
        '-p',
        type=int,
        required=False,
        default=5000,
        help='Port the server should use',
    )
    Flags.PARSER.add_argument(
        '--environment',
        '-e',
        required=False,
        type=str,
        default='',
        help='The Zenysis environment that the server should use. '
        'Can optionally be specified by setting the `ZEN_ENV` environment '
        'variable. The environment variable will take precedence over '
        'the command-line argument.',
        choices=VALID_MODULES,
    )
    Flags.PARSER.add_argument(
        '--db-check',
        action='store_true',
        required=False,
        default=False,
        help='Override other settings and do perform db schema version check',
    )
    Flags.PARSER.add_argument(
        '--skip-db-check',
        action='store_true',
        required=False,
        default=False,
        help='Whether to skip a check to be running on matching db schema version',
    )
    Flags.PARSER.add_argument(
        '--force-druid-db-update',
        action='store_true',
        required=False,
        default=False,
        help='Force populating druid metadata in the db even if it was recently updated',
    )
    Flags.InitArgs()

    environment = (
        Flags.ARGS.environment if Flags.ARGS.environment else os.getenv('ZEN_ENV')
    )
    if not environment:
        raise ValueError(
            'The Zenysis environment that the server should use is not set. '
            'It can optionally be specified by setting the `ZEN_ENV` environment '
            'variable or passing the environment flag.'
        )

    # An instance config is not required in dev, so we don't want to print an error if
    # it is missing.
    instance_config = load_instance_configuration_from_file(log_missing=False)

    ensure_dev_hasura_admin_secret()

    # Create the default flask configuration. Apply any instance config overrides the
    # dev might be using locally.
    flask_config = build_flask_config(environment)

    # If no db_name flag was set, use the default database name for this deployment.
    db_name = Flags.ARGS.db_name or f'{environment}-local'

    # Make sure Postgres has been started on the developers machine.
    if not Flags.ARGS.db_uri:
        start_postgres()

    # NOTE: For ease of development, make sure hasura graphql docker services
    # are running and using the correct DB.
    os.system(f'scripts/db/hasura/dev/start_hasura.sh {db_name}')

    app = create_app(
        flask_config,
        instance_config,
        environment,
        not Flags.ARGS.db_check
        and (Flags.ARGS.skip_db_check or os.environ.get('ZEN_SKIP_DB_CHECK')),
        Flags.ARGS.force_druid_db_update,
    )
    app.run(host='0.0.0.0', port=Flags.ARGS.port, reloader_type='zenysis_watchdog')


if __name__ == '__main__':
    sys.exit(main())
