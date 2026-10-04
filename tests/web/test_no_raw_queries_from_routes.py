'''SEC-4 guard: request-serving code reaches Druid only through the policy client.

Druid access without the caller's query policy comes from a few capabilities: the
system query client, raw Druid dicts, the druid_context lookups, and the modules
that build or run Druid queries directly. This test scans the request-serving
trees for any use of those capabilities and fails unless an entry below says why
the use cannot leak data past a policy.

Scope: one hop. A scanned module is flagged when it touches a capability itself.
A helper outside SCANNED_DIRS that touches one is caught only where a scanned
module imports that helper's module (see DRUID_MODULES).
'''

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = (
    'web/server/routes',
    'web/server/api',
    'web/server/query',
    'web/server/util',
)

# Importing anything from these modules gives policy-free Druid access.
DRUID_MODULES = (
    'data.pydruid_query',
    'db.druid.metadata',
    'db.druid.query_client',
    'pydruid.client',
    'web.server.data.dimension_metadata',
    'web.server.data.dimension_values',
    'web.server.data.druid_context',
    'web.server.data.row_count',
    'web.server.data.status',
    'web.server.data.status_page',
    'web.server.data.time_boundary',
)

# druid_context attributes that name the datasource and run no data query.
DATASOURCE_IDENTITY = {
    'available_datasources',
    'current_datasource',
    'current_db_datasource',
    'datasource_config',
}

_FIELD_ROWS = 'Every lookup ANDs the caller policy into the field filter, and only '
_FIELD_ROWS += 'callers without a policy share the row-count cache '
_FIELD_ROWS += '(tests/web/test_field_info_route.py).'

# (file, enclosing scope, capability) -> why it cannot leak data past a policy.
ALLOWLIST = {
    (
        'web/server/routes/views/field.py',
        '_FieldRows.__init__',
        'druid_context.data_time_boundary',
    ): _FIELD_ROWS,
    (
        'web/server/routes/views/field.py',
        '_FieldRows.__init__',
        'druid_context.row_count_lookup',
    ): _FIELD_ROWS,
    (
        'web/server/routes/views/health_check.py',
        'HealthCheck.run',
        'druid_context.druid_metadata',
    ): 'Fixed liveness query with no user input; returns only success or 503.',
    (
        'web/server/query/request/query_request.py',
        'QueryRequest.build_intervals',
        'druid_context.data_time_boundary',
    ): 'Datasource-wide interval for an all-time filter; it bounds a query that '
    'runs through the policy client. Its end date is datasource-wide, like the '
    'dates in KNOWN_VIOLATIONS.',
    (
        'web/server/query/data_quality/data_quality_report.py',
        'DataQualityReport.get_no_date_filter_df',
        'druid_context.data_time_boundary',
    ): 'Datasource-wide interval bounding a query run through self.query_client, '
    'the policy client.',
    (
        'web/server/routes/views/data_upload_summary.py',
        '',
        'import web.server.data.status.MIN_TIME_FIELD',
    ): 'String constant (a dict key); runs nothing.',
    (
        'web/server/routes/views/data_upload_summary.py',
        '',
        'import web.server.data.status.MAX_TIME_FIELD',
    ): 'String constant (a dict key); runs nothing.',
    (
        'web/server/util/dev/static_data_query_client.py',
        '',
        'import db.druid.query_client.DruidQueryClient_',
    ): 'Dev-only system-client substitute; nothing imports this module.',
    (
        'web/server/util/dev/static_data_query_client.py',
        'StaticDataQueryClient.run_raw_query',
        'run_raw_query',
    ): 'Dev-only system-client substitute; nothing imports this module.',
}

# Uses that do leak past a policy today. Each must still be present: when one is
# fixed this test fails, and the entry moves to ALLOWLIST or is deleted.
_DATASOURCE_DATES = 'Datasource-wide data dates or source status, shown regardless '
_DATASOURCE_DATES += "of the viewer's policy (SEC-4 open item 2)."
KNOWN_VIOLATIONS = {
    (
        'web/server/routes/views/data_upload_summary.py',
        'get_source_date_range',
        'druid_context.data_status_information',
    ): _DATASOURCE_DATES,
    (
        'web/server/routes/index.py',
        '',
        'import web.server.data.status_page.get_status_page_data',
    ): _DATASOURCE_DATES,
    (
        'web/server/util/template_renderer.py',
        'TemplateRenderer.build_ui_params',
        'druid_context.data_status_information',
    ): _DATASOURCE_DATES,
    (
        'web/server/util/template_renderer.py',
        'TemplateRenderer.build_ui_params',
        'druid_context.data_time_boundary',
    ): _DATASOURCE_DATES,
    (
        'web/server/util/template_renderer.py',
        'TemplateRenderer.build_template_params',
        'druid_context.data_status_information',
    ): _DATASOURCE_DATES,
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return None


def _druid_module(module: str) -> str | None:
    for druid_module in DRUID_MODULES:
        if module == druid_module or module.startswith(f'{druid_module}.'):
            return druid_module
    return None


def _names_druid_context(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == 'druid_context') or (
        isinstance(node, ast.Attribute) and node.attr == 'druid_context'
    )


def _capabilities(node: ast.AST, parent: ast.AST | None) -> Iterator[str]:
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        if _druid_module(node.module):
            for alias in node.names:
                yield f'import {node.module}.{alias.name}'
        elif node.module in {m.rsplit('.', 1)[0] for m in DRUID_MODULES}:
            for alias in node.names:
                if _druid_module(f'{node.module}.{alias.name}'):
                    yield f'import {node.module}.{alias.name}'
        return
    if isinstance(node, ast.Import):
        for alias in node.names:
            if _druid_module(alias.name):
                yield f'import {alias.name}'
        return
    if isinstance(node, ast.Name) and node.id == 'system_query_client':
        yield node.id
        return
    if isinstance(node, ast.Attribute):
        if node.attr in ('system_query_client', 'run_raw_query'):
            yield _dotted(node) or node.attr
            return
        # AuthorizedQueryClient wraps the system client as _query_client.
        if node.attr == '_query_client' and _dotted(node.value) != 'self':
            yield _dotted(node) or node.attr
            return
    if not _names_druid_context(node):
        return
    # The assignment that names the local `druid_context` is followed through
    # that name's own uses; any other alias or hand-off is flagged.
    if isinstance(parent, ast.Assign) and [
        _dotted(target) for target in parent.targets
    ] == ['druid_context']:
        return
    if isinstance(parent, ast.Attribute) and parent.value is node:
        if parent.attr not in DATASOURCE_IDENTITY:
            yield f'druid_context.{parent.attr}'
        return
    yield 'druid_context'


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
        for capability in _capabilities(node, parent):
            self.findings.add((self.path, '.'.join(self.scope), capability))
        self.parents.append(node)
        super().visit(node)
        self.parents.pop()


def _scan(source: str, path: str = 'example.py') -> set[tuple[str, str, str]]:
    scanner = _Scanner(path)
    scanner.visit(ast.parse(source, path))
    return scanner.findings


def _findings() -> set[tuple[str, str, str]]:
    findings = set()
    for directory in SCANNED_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT).as_posix()
            findings |= _scan(path.read_text(), relative)
    return findings


def test_request_code_does_not_reach_druid_around_the_query_policy():
    unexpected = sorted(_findings() - set(ALLOWLIST) - set(KNOWN_VIOLATIONS))
    assert not unexpected, (
        'Request-serving code reaches Druid without the caller policy (SEC-4). Use '
        'current_app.query_client.run_query, or add an ALLOWLIST entry that says '
        f'why this cannot leak data: {unexpected}'
    )


def test_allowlist_has_no_stale_entries():
    assert not set(ALLOWLIST) - _findings()


def test_known_violations_are_still_present():
    fixed = set(KNOWN_VIOLATIONS) - _findings()
    assert not fixed, f'Fixed: move these to ALLOWLIST or delete them: {fixed}'


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
        'from db.druid.query_client import DruidQueryClient',
        'from db.druid.query_client import DruidQueryClient_ as Client',
        'import db.druid.query_client',
        'from db.druid import query_client',
        'from data.pydruid_query.pydruid_query import PyDruidQuery',
        'from db.druid.metadata import DruidMetadata',
        'from web.server.data.row_count import RowCountLookup',
        'from web.server.data.time_boundary import DataTimeBoundary',
        'from web.server.data.status_page import get_status_page_data',
        'from pydruid.client import PyDruid',
    ],
)
def test_scanner_flags_each_capability(source):
    assert _scan(source)


@pytest.mark.parametrize(
    'source',
    [
        'current_app.druid_context.current_datasource.name',
        'druid_context = current_app.druid_context\ndruid_context.current_datasource',
        'current_app.query_client.run_query(q)',
        'from db.druid.query_builder import GroupByQueryBuilder',
        'from db.druid import util',
    ],
)
def test_scanner_allows_policy_client_and_datasource_identity(source):
    assert not _scan(source)
