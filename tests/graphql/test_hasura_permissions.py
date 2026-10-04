'''Pins the Hasura role permissions that WP-0a grants (SEC-2).

Any change to who can do what through `/api/graphql` must change this file
too, so it shows up in review. `scripts/db/hasura/check_role_permissions.py`
proves against a live Hasura that these permissions cover the compiled Relay
operations; this test needs no Hasura.
'''

import os

import yaml

TABLES_YAML = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'graphql',
    'hasura',
    'metadata',
    'versions',
    'latest',
    'tables.yaml',
)
OPERATIONS = {
    'insert_permissions': 'insert',
    'select_permissions': 'select',
    'update_permissions': 'update',
    'delete_permissions': 'delete',
}

USER_GRANTS = {
    'category': {'insert', 'select', 'update', 'delete'},
    'data_upload_file_summary': {'insert', 'select', 'update', 'delete'},
    'dataprep_flow': {'insert', 'select', 'update', 'delete'},
    'dataprep_job': {'select', 'delete'},
    'dimension': {'select'},
    'dimension_category': {'select'},
    'dimension_category_mapping': {'select'},
    'field': {'insert', 'select', 'update', 'delete'},
    'field_category_mapping': {'insert', 'select', 'update'},
    'field_dimension_mapping': {'select'},
    'field_pipeline_datasource_mapping': {'insert', 'select'},
    'pipeline_datasource': {'insert', 'select', 'update'},
    'pipeline_run_metadata': {'select'},
    'self_serve_source': {'insert', 'select', 'update', 'delete'},
    'unpublished_field': {'insert', 'select', 'update', 'delete'},
    'unpublished_field_category_mapping': {'insert', 'select', 'delete'},
    'unpublished_field_pipeline_datasource_mapping': {'insert', 'select', 'update'},
}
ANONYMOUS_SELECT_COLUMNS = {
    'dimension': ['description', 'id', 'name'],
    'dimension_category': ['id', 'name'],
    'dimension_category_mapping': ['id'],
}
USER_AGGREGATIONS = {
    'category',
    'field_category_mapping',
    'unpublished_field_pipeline_datasource_mapping',
}


def load_permissions():
    with open(TABLES_YAML) as tables_file:
        tables = yaml.safe_load(tables_file)
    for entry in tables:
        table = entry['table']['name']
        for key, operation in OPERATIONS.items():
            for grant in entry.get(key, []):
                yield grant['role'], table, operation, grant['permission']


def test_only_user_and_anonymous_roles_are_granted():
    assert {role for role, *_ in load_permissions()} == {'user', 'anonymous'}


def test_user_grants_are_exactly_what_the_ui_uses():
    grants = {}
    for role, table, operation, _ in load_permissions():
        if role == 'user':
            grants.setdefault(table, set()).add(operation)
    assert grants == USER_GRANTS


def test_anonymous_reads_only_the_public_query_columns():
    grants = {
        (table, operation): permission
        for role, table, operation, permission in load_permissions()
        if role == 'anonymous'
    }
    assert set(grants) == {(table, 'select') for table in ANONYMOUS_SELECT_COLUMNS}
    for (table, _), permission in grants.items():
        assert sorted(permission['columns']) == ANONYMOUS_SELECT_COLUMNS[table]
        assert not permission.get('allow_aggregations')


def test_user_aggregations_only_where_compiled_operations_count():
    tables = {
        table
        for role, table, operation, permission in load_permissions()
        if role == 'user' and operation == 'select'
        if permission.get('allow_aggregations')
    }
    assert tables == USER_AGGREGATIONS


def test_no_insert_is_backend_only():
    for _, _, operation, permission in load_permissions():
        if operation == 'insert':
            assert permission.get('backend_only') is False
