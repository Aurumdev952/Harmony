'''SEC-4 guard: request handlers reach Druid only through the policy-applying client.

The system query client, raw Druid dicts and the druid_context lookups run with no
query policy. Code under web/server/routes and web/server/api takes user input, so
it may use them only where an allowlist entry below says why that is safe.
'''

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ('web/server/routes', 'web/server/api')

# druid_context attributes that name the datasource and run no data query.
DATASOURCE_IDENTITY = {
    'available_datasources',
    'current_datasource',
    'current_db_datasource',
    'datasource_config',
}

# (file, enclosing scope, expression) -> why it cannot leak data past a policy.
ALLOWLIST = {
    (
        'web/server/routes/views/field.py',
        '_FieldRows.__init__',
        'druid_context.data_time_boundary',
    ): 'Every filtered lookup ANDs the caller policy; the full interval only '
    'bounds the query (tests/web/test_field_info_route.py).',
    (
        'web/server/routes/views/field.py',
        '_FieldRows.__init__',
        'druid_context.row_count_lookup',
    ): 'Filter carries the caller policy; the shared cache is used only by '
    'callers without one (tests/web/test_field_info_route.py).',
    (
        'web/server/routes/views/health_check.py',
        'HealthCheck.run',
        'druid_context.druid_metadata',
    ): 'Fixed liveness query with no user input; returns only success or 503.',
    (
        'web/server/routes/views/data_upload_summary.py',
        'get_source_date_range',
        'druid_context.data_status_information',
    ): 'Datasource-wide per-source date ranges with no policy: SEC-4 open item 2 '
    '(WP-4e decides whether dates are policy-scoped).',
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return None


def _names_druid_context(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == 'druid_context') or (
        isinstance(node, ast.Attribute) and node.attr == 'druid_context'
    )


def _unsafe_expression(node: ast.AST, parent: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name) and node.id == 'system_query_client':
        return node.id
    if isinstance(node, ast.Attribute):
        if node.attr in ('system_query_client', 'run_raw_query'):
            return _dotted(node) or node.attr
        # AuthorizedQueryClient wraps the system client as _query_client.
        if node.attr == '_query_client' and _dotted(node.value) != 'self':
            return _dotted(node) or node.attr
    if not _names_druid_context(node):
        return None
    # A druid_context alias is followed through its own Name nodes; only the
    # assignment that creates it is exempt.
    if isinstance(parent, ast.Assign) and [
        _dotted(target) for target in parent.targets
    ] == ['druid_context']:
        return None
    if isinstance(parent, ast.Attribute) and parent.value is node:
        if parent.attr in DATASOURCE_IDENTITY:
            return None
        return f'druid_context.{parent.attr}'
    return 'druid_context'


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.scope: list[str] = []
        self.parents: list[ast.AST] = []
        self.findings: set[tuple[str, str, str]] = set()

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _visit_scope

    def visit(self, node):
        parent = self.parents[-1] if self.parents else None
        expression = _unsafe_expression(node, parent)
        if expression:
            self.findings.add((self.path, '.'.join(self.scope), expression))
        self.parents.append(node)
        super().visit(node)
        self.parents.pop()


def _scan(source: str, path: str = 'example.py') -> set[tuple[str, str, str]]:
    scanner = _Scanner(path)
    scanner.visit(ast.parse(source, path))
    return scanner.findings


def _findings() -> Iterator[tuple[str, str, str]]:
    for directory in SCANNED_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT).as_posix()
            yield from _scan(path.read_text(), relative)


def test_routes_do_not_reach_druid_around_the_query_policy():
    unexpected = sorted(set(_findings()) - set(ALLOWLIST))
    assert not unexpected, (
        'Route or API code reaches Druid without the caller policy (SEC-4). Use '
        'current_app.query_client.run_query, or add an ALLOWLIST entry that says '
        f'why this cannot leak data: {unexpected}'
    )


def test_allowlist_has_no_stale_entries():
    assert not set(ALLOWLIST) - set(_findings())


@pytest.mark.parametrize(
    'source',
    [
        'current_app.system_query_client.run_query(q)',
        'current_app.druid_context.row_count_lookup.get_row_count(f, k)',
        (
            'druid_context = current_app.druid_context\n'
            'druid_context.data_time_boundary.get_filtered_time_boundary(f)'
        ),
        'lookup = current_app.druid_context.data_time_boundary\nlookup.get_x(f)',
        'ctx = current_app.druid_context\nctx.row_count_lookup.get_row_count(f)',
        'helper(current_app.druid_context)',
        'client.run_raw_query({})',
        'current_app.query_client._query_client.run_query(q)',
    ],
)
def test_scanner_flags_each_unsafe_form(source):
    assert _scan(source)


@pytest.mark.parametrize(
    'source',
    [
        'current_app.druid_context.current_datasource.name',
        'druid_context = current_app.druid_context\ndruid_context.current_datasource',
        'current_app.query_client.run_query(q)',
    ],
)
def test_scanner_allows_policy_and_datasource_identity_uses(source):
    assert not _scan(source)
