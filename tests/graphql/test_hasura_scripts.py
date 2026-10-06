'''The Hasura scripts load only plain YAML, and send the admin secret only to a
checked host and never through a redirect.'''

from __future__ import annotations

import http.server
import importlib.util
import sys
import threading
import types
import urllib.error
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
import yaml
from pylib.base.flags import build_parser

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts' / 'db' / 'hasura'


def _load_script(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name='apply_metadata_snapshot')
def fixture_apply_metadata_snapshot() -> types.ModuleType:
    return _load_script('apply_metadata_snapshot')


@pytest.fixture(name='check_role_permissions')
def fixture_check_role_permissions(monkeypatch) -> types.ModuleType:
    # The script's graphql-core comes from its PEP 723 header, not the project
    # environment, where `graphql` is the repository's schema folder.
    graphql = types.ModuleType('graphql')
    for name in (
        'GraphQLSchema',
        'OverlappingFieldsCanBeMergedRule',
        'build_client_schema',
        'parse',
        'print_schema',
        'validate',
    ):
        setattr(graphql, name, mock.MagicMock(name=name))
    graphql.get_introspection_query = lambda: '{ __schema { types { name } } }'
    graphql.specified_rules = []
    monkeypatch.setitem(sys.modules, 'graphql', graphql)
    return _load_script('check_role_permissions')


def test_metadata_snapshot_has_no_custom_yaml_tags(apply_metadata_snapshot):
    # safe_load must read the checked-in metadata exactly as the unsafe loader did.
    expected = {}
    for path in sorted(Path(apply_metadata_snapshot.METADATA_FOLDER).glob('*.yaml')):
        data = yaml.load(path.read_text(), Loader=yaml.Loader)  # noqa: S506
        expected.update(data if isinstance(data, dict) else {path.stem: data})
    assert apply_metadata_snapshot.build_metadata_dict() == expected


def test_metadata_snapshot_refuses_python_tags(
    apply_metadata_snapshot, monkeypatch, tmp_path
):
    (tmp_path / 'tables.yaml').write_text(
        "!!python/object/apply:os.system ['echo pwned']\n"
    )
    monkeypatch.setattr(apply_metadata_snapshot, 'METADATA_FOLDER', str(tmp_path))
    with pytest.raises(yaml.constructor.ConstructorError):
        apply_metadata_snapshot.build_metadata_dict()


@pytest.fixture(name='redirecting_server')
def fixture_redirecting_server() -> Iterator[tuple[str, list[str]]]:
    '''Serve 200 on /healthz and /elsewhere, and a cross-host 302 to /elsewhere on
    every other path. Yields the base URL and the paths requested so far.'''
    paths: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _respond(self) -> None:
            paths.append(self.path)
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if self.path in ('/healthz', '/elsewhere'):
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
                return
            self.send_response(302)
            port = self.server.server_address[1]
            self.send_header('Location', f'http://localhost:{port}/elsewhere')
            self.send_header('Content-Length', '0')
            self.end_headers()

        do_GET = do_POST = _respond

        def log_message(self, *args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}', paths
    server.shutdown()
    server.server_close()


def test_metadata_snapshot_does_not_follow_redirects(
    apply_metadata_snapshot, monkeypatch, redirecting_server
):
    base_url, paths = redirecting_server
    monkeypatch.setattr(apply_metadata_snapshot.Flags, 'PARSER', build_parser())
    monkeypatch.setattr(sys, 'argv', ['apply', '--hasura_host', base_url])
    monkeypatch.setenv('HASURA_ADMIN_SECRET', 'secret')
    assert apply_metadata_snapshot.main() == 1
    assert paths == ['/healthz', '/v1/metadata']


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('http://localhost:8088/', 'http://localhost:8088'),
        ('http://127.0.0.1:8088', 'http://127.0.0.1:8088'),
        ('http://[::1]:8088', 'http://[::1]:8088'),
        ('http://hasura:8080', 'http://hasura:8080'),
        ('https://hasura.example.org/prefix/', 'https://hasura.example.org/prefix'),
    ],
)
def test_check_role_permissions_accepts_hasura_hosts(
    check_role_permissions, raw, expected
):
    assert check_role_permissions.parse_hasura_host(raw) == expected


@pytest.mark.parametrize(
    'raw',
    [
        'file:///etc/passwd',
        'ftp://hasura:21',
        'localhost:8088',
        'http://',
        'http://hasura.example.org',
        'https://user:password@hasura.example.org',
        'https://hasura.example.org?x=1',
        'https://hasura.example.org#x',
    ],
)
def test_check_role_permissions_refuses_other_hosts(
    check_role_permissions, monkeypatch, raw
):
    monkeypatch.setattr(sys, 'argv', ['check', '--hasura_host', raw])
    monkeypatch.setenv('HASURA_ADMIN_SECRET', 'secret')
    with mock.patch.object(check_role_permissions, '_OPENER') as opener:
        assert check_role_permissions.main() == 2
    opener.open.assert_not_called()


def test_check_role_permissions_does_not_follow_redirects(
    check_role_permissions, redirecting_server
):
    base_url, paths = redirecting_server
    with pytest.raises(urllib.error.HTTPError) as error:
        check_role_permissions.fetch_schema(base_url, 'secret', 'user')
    assert error.value.code == 302
    assert paths == ['/v1beta1/relay']
