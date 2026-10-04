#!/usr/bin/env python
'''Replay every compiled Relay operation through the Flask /api/graphql proxy.

Runs the real Flask app in-process as a signed-in user and posts each operation
in `web/client/**/__generated__` with variables shaped like the UI sends,
mutations included. The normalised responses are written to `--out`. Pass
`--compare` with an earlier output to diff two runs, for example main's proxy on
Hasura v2.11 against this branch's proxy on Hasura v2.45.

It creates, edits and deletes catalog, field setup and data upload rows, so it
refuses to run unless `--disposable-database` is passed and the database is
marked disposable:

    COMMENT ON DATABASE "<name>" IS 'harmony-disposable';

Environment: ZEN_ENV, DATABASE_URL, HASURA_HOST, HASURA_ADMIN_SECRET (branch
code only), SERVER_SOFTWARE=gunicorn so the app registers its routes, and
REPLAY_USERNAME / REPLAY_PASSWORD for an active user.
'''
import argparse
import base64
import glob
import json
import os
import re
import sys

import psycopg2

from web.server.app import create_app

DISPOSABLE_MARKER = 'harmony-disposable'
# Dataprep recipe ids are positive, so a negative one cannot match a real flow.
REPLAY_RECIPE_ID = -424242
TEXT = re.compile(r'"text": ("(?:[^"\\]|\\.)*")')
NAME = re.compile(r'^(?:query|mutation)\s+(\w+)')
TIMESTAMP_KEY = re.compile(r'(^created$|last_?modified)', re.IGNORECASE)


def load_operations():
    ops = {}
    for path in glob.glob('web/client/**/__generated__/*.graphql.js', recursive=True):
        with open(path) as handle:
            for literal in TEXT.findall(handle.read()):
                text = json.loads(literal)
                ops[NAME.match(text).group(1)] = text
    return ops


def relay_id(table, pk):
    return base64.b64encode(
        f'[1, "public", {json.dumps(table)}, {json.dumps(pk)}]'.encode()
    ).decode()


def normalise(value):
    if isinstance(value, dict):
        return {
            k: normalise(v) for k, v in value.items() if not TIMESTAMP_KEY.search(k)
        }
    if isinstance(value, list):
        return [normalise(v) for v in value]
    return value


CALC = {'type': 'SUM', 'filter': {'type': 'FIELD', 'fieldId': 'wp0a_field'}}
NOW = '2026-10-04T00:00:00'


def unpublished(field_id):
    return {
        'unpublished_field': {
            'data': {
                'calculation': CALC,
                'id': field_id,
                'name': field_id,
                'short_name': field_id,
            },
            'on_conflict': {
                'constraint': 'unpublished_field_pkey',
                'update_columns': ['name', 'short_name'],
            },
        }
    }


def self_serve_source(source_id, unpublished_ids, dataprep, source_pk=None):
    source = {
        'data_upload_file_summaries': {
            'data': [
                {
                    'column_mapping': [],
                    'created': NOW,
                    'file_path': f'/uploads/{source_id}.csv',
                    'last_modified': NOW,
                    'source_id': source_id,
                    'user_file_name': f'{source_id}.csv',
                }
            ],
            'on_conflict': {
                'constraint': 'data_upload_file_summary_pkey',
                'update_columns': ['column_mapping', 'last_modified'],
            },
        },
        'dataprep_flow': {
            'data': {
                'appendable': True,
                'expected_columns': [],
                'recipe_id': REPLAY_RECIPE_ID,
            },
            'on_conflict': {
                'constraint': 'dataprep_flow_recipe_id_key',
                'update_columns': ['appendable', 'expected_columns', 'recipe_id'],
            },
        }
        if dataprep
        else None,
        'last_modified': NOW,
        'pipeline_datasource': {
            'data': {
                'id': source_id,
                'name': source_id,
                'unpublished_field_pipeline_datasource_mappings': {
                    'data': [unpublished(f) for f in unpublished_ids],
                    'on_conflict': {
                        'constraint': (
                            'unpublished_field_pipeline_da_unpublished_field_id_pipeline_key'
                        ),
                        'update_columns': [],
                    },
                },
            },
            'on_conflict': {
                'constraint': 'pipeline_datasource_pkey',
                'update_columns': ['name'],
            },
        },
    }
    if source_pk is not None:
        source['id'] = source_pk
    return source


def steps(state):
    field = relay_id('field', 'wp0a_field')
    group = relay_id('category', 'wp0a_group')
    pipeline = {
        'allSourcesName': 'All sources',
        'timeWindow': '2020-01-01T00:00:00',
        'unsuccessfulFilter': {},
    }
    yield 'CreateGroupModalMutation', {
        'id': 'wp0a_group',
        'name': 'Group',
        'parentCategoryId': 'root',
    }
    yield 'CreateGroupModalMutation', {
        'id': 'wp0a_group2',
        'name': 'Group 2',
        'parentCategoryId': 'root',
    }
    yield 'EditGroupModalMutation', {
        'dbCategoryId': 'wp0a_group',
        'newCategoryName': 'Group renamed',
    }
    yield 'CategoryGroupRowValueMutation', {
        'dbId': 'wp0a_group',
        'newName': 'Group',
        'newVisibilityStatus': 'VISIBLE',
    }
    yield 'CreateCalculationIndicatorViewMutation', {
        'id': 'wp0a_field',
        'name': 'Field',
        'shortName': 'F',
        'description': 'd',
        'calculation': CALC,
        'categoryObj': [{'category_id': 'wp0a_group'}],
        'isCopy': False,
        'isNotCopy': True,
        'copiedFromFieldId': '',
    }
    yield 'CreateCalculationIndicatorViewMutation', {
        'id': 'wp0a_copy',
        'name': 'Copy',
        'shortName': 'C',
        'description': 'd',
        'calculation': CALC,
        'categoryObj': [{'category_id': 'wp0a_group'}],
        'isCopy': True,
        'isNotCopy': False,
        'copiedFromFieldId': 'wp0a_field',
    }
    yield 'NameRowMutation', {'dbId': 'wp0a_field', 'newName': 'Field 2'}
    yield 'DescriptionRowMutation', {'dbId': 'wp0a_field', 'newDescription': 'd2'}
    yield 'ShortNameRowMutation', {'dbId': 'wp0a_field', 'newShortName': 'F2'}
    yield 'CalculationRowMutation', {'dbId': 'wp0a_field', 'newCalculation': CALC}
    yield 'FieldCalculationSectionMutation', {
        'dbId': 'wp0a_field',
        'newCalculation': CALC,
    }
    yield 'VisibilityRowMutation', {
        'dbCategoryId': 'wp0a_group',
        'dbFieldId': 'wp0a_field',
        'newVisibilityStatus': 'VISIBLE',
    }
    yield 'FieldRowValueMutation', {
        'categoryId': 'wp0a_group',
        'dbId': 'wp0a_field',
        'newDescription': 'd3',
        'newName': 'Field 3',
        'newVisibilityStatus': 'VISIBLE',
    }
    yield 'useParentCategoryChangeForFieldMutation', {
        'dbFieldId': 'wp0a_field',
        'dbNewParentCategoryId': 'wp0a_group2',
        'dbOriginalParentCategoryId': 'wp0a_group',
        'insertNewMapping': False,
    }
    yield 'useParentCategoryChangeForFieldMutation', {
        'dbFieldId': 'wp0a_copy',
        'dbNewParentCategoryId': 'wp0a_group2',
        'dbOriginalParentCategoryId': None,
        'insertNewMapping': True,
    }
    yield 'useParentCategoryChangeForCategoryMutation', {
        'dbCategoryId': 'wp0a_group2',
        'dbNewParentCategoryId': 'wp0a_group',
    }
    yield 'useBatchParentCategoryChangeMutation', {
        'dbCategoryIds': ['wp0a_group2'],
        'dbFieldIds': ['wp0a_field'],
        'dbNewParentCategoryId': 'wp0a_group3',
        'dbOriginalParentCategoryId': 'root',
        'insertNewCategory': True,
        'insertNewMapping': False,
        'newFieldMappingObjects': [],
        'newParentCategoryName': 'Group 3',
    }
    yield 'useSelfServeMutation', {
        'fileSummariesToUnlink': [],
        'insertNewSource': True,
        'selfServeSource': self_serve_source(
            'wp0a_src', ['wp0a_unpub', 'wp0a_unpub2'], False
        ),
    }
    yield 'useSelfServeMutation', {
        'fileSummariesToUnlink': [],
        'insertNewSource': True,
        'selfServeSource': self_serve_source('wp0a_prep', ['wp0a_unpub3'], True),
    }
    yield 'useSelfServeMutation', lambda: {
        'fileSummariesToUnlink': [state['file_summary']],
        'insertNewSource': False,
        'selfServeSource': self_serve_source(
            'wp0a_src', ['wp0a_unpub'], False, state['source_pk']
        ),
    }
    yield 'NameInputMutation', {'fieldId': 'wp0a_unpub', 'name': 'Unpub'}
    yield 'ShortNameInputMutation', {'fieldId': 'wp0a_unpub', 'shortName': 'U'}
    yield 'DescriptionInputMutation', {'fieldId': 'wp0a_unpub', 'description': 'ud'}
    yield 'CalculationInputMutation', {'fieldId': 'wp0a_unpub', 'calculation': CALC}
    yield 'UpdateCalculationActionMutation', {'id': 'wp0a_unpub', 'calculation': CALC}
    yield 'CategoryInputMutation', {
        'categoryId': 'wp0a_group',
        'unpublishedFieldId': 'wp0a_unpub',
    }
    yield 'UpdateCategoryActionMutation', {
        'fieldCategoryMappingObjs': [
            {'unpublished_field_id': 'wp0a_unpub2', 'category_id': 'wp0a_group'}
        ],
        'fieldIds': ['wp0a_unpub2'],
    }
    for name in [
        'BatchPublishModalContentsQuery',
        'UnpublishedFieldsTableContainerQuery',
        'DataStatusPageQuery',
        'DataStatusPageSelfServeQuery',
        'useDatasourceLookupQuery',
    ]:
        yield name, {}
    yield 'UnpublishedFieldTableRowsQuery', {'pageSize': 10, 'searchText': ''}
    yield 'UnpublishedFieldTableRowsPaginationQuery', {
        'first': 10,
        'after': None,
        'searchText': 'wp0a',
    }
    yield 'BatchPublishModalMutation', {
        'fieldIds': ['wp0a_unpub'],
        'fieldObjects': [
            {
                'id': 'wp0a_unpub',
                'name': 'Unpub',
                'short_name': 'U',
                'description': 'ud',
                'calculation': CALC,
                'field_category_mappings': {'data': [{'category_id': 'wp0a_group'}]},
                'field_pipeline_datasource_mappings': {
                    'data': [{'pipeline_datasource_id': 'wp0a_src'}]
                },
            }
        ],
    }
    yield 'UnpublishedFieldRowMutation', {
        'id': 'wp0a_unpub2',
        'name': 'Unpub 2',
        'shortName': 'U2',
        'description': None,
        'calculation': CALC,
        'fieldCategoryMappings': [{'category_id': 'wp0a_group'}],
        'fieldPipelineDatasourceMappings': [{'pipeline_datasource_id': 'wp0a_src'}],
    }
    for name in [
        'BreadcrumbPathQuery',
        'CreateCalculationIndicatorViewQuery',
        'EditableCalculationQuery',
        'QueryBuilderQuery',
        'patchDimensionServiceQuery',
        'patchFieldMetadataServiceQuery',
        'patchFieldServiceQuery',
        'useFieldHierarchyRootQuery',
    ]:
        yield name, {}
    for name in [
        'CopyIndicatorViewWrapperQuery',
        'FieldAboutPanelQuery',
        'FieldDetailsPageQuery',
    ]:
        yield name, {'id': field}
    for name in [
        'BreadcrumbLeafItemQuery',
        'DirectoryTableContainerQuery',
        'RecursiveCategoryBreadcrumbQuery',
    ]:
        yield name, {'id': group}
    yield 'usePipelineTimesHistoricalPipelinesQuery', pipeline
    yield 'usePipelineTimesLastPipelineQuery', {'allSourcesName': 'All sources'}
    yield 'usePipelineTimesLastSuccessfulPipelineQuery', {
        'allSourcesName': 'All sources',
        'unsuccessfulFilter': {},
    }
    yield 'DeleteFieldModalMutation', {'dbFieldId': 'wp0a_copy'}
    yield 'useDeleteSourceMutation', lambda: {
        'selfServeSourceId': state['prep_pk'],
        'sourceId': 'wp0a_prep',
        'isDataprep': True,
        'dataprepFlowId': state['prep_flow'],
    }
    yield 'useDeleteSourceMutation', lambda: {
        'selfServeSourceId': state['source_pk'],
        'sourceId': 'wp0a_src',
        'isDataprep': False,
        'dataprepFlowId': 0,
    }
    yield 'DeleteCategoryModalMutation', {'dbCategoryId': 'wp0a_group3'}


def lookup(sql, *args):
    with psycopg2.connect(os.environ['DATABASE_URL']) as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def database_is_marked_disposable():
    comment = lookup(
        'select shobj_description(oid, %s) from pg_database '
        'where datname = current_database()',
        'pg_database',
    )
    return comment == DISPOSABLE_MARKER


class GeneratedIds(dict):
    '''Serial ids the UI would read from earlier responses, fetched on demand.'''

    QUERIES = {
        'source_pk': (
            'select id from self_serve_source where source_id = %s',
            'wp0a_src',
        ),
        'prep_pk': (
            'select id from self_serve_source where source_id = %s',
            'wp0a_prep',
        ),
        'prep_flow': (
            'select dataprep_flow_id from self_serve_source where source_id = %s',
            'wp0a_prep',
        ),
        'file_summary': (
            'select min(id) from data_upload_file_summary where source_id = %s',
            'wp0a_src',
        ),
    }

    def __missing__(self, key):
        return lookup(*self.QUERIES[key])


def replay(out_path):
    ops = load_operations()
    app = create_app(skip_db_check=True)
    app.config['HASURA_HOST'] = os.environ['HASURA_HOST']
    client = app.test_client()
    credentials = {
        'X-Username': os.environ['REPLAY_USERNAME'],
        'X-Password': os.environ['REPLAY_PASSWORD'],
    }
    results = []
    for name, variables in steps(GeneratedIds()):
        if callable(variables):
            variables = variables()
        response = client.post(
            '/api/graphql',
            json={'query': ops[name], 'variables': variables},
            headers=credentials,
        )
        try:
            body = json.loads(response.data)
        except ValueError:
            body = {'raw': response.data.decode()[:300]}
        results.append(
            {'operation': name, 'status': response.status_code, 'body': normalise(body)}
        )
        print(response.status_code, name, 'errors' if 'errors' in body else 'ok')

    replayed = {result['operation'] for result in results}
    failures = [r for r in results if r['status'] != 200 or 'errors' in r['body']]
    print(
        f'{len(results)} steps, {len(failures)} failed, not replayed: {sorted(set(ops) - replayed)}'
    )
    with open(out_path, 'w') as handle:
        json.dump(results, handle, indent=1, sort_keys=True)
    return results


def differences(before, after, prefix=''):
    if type(before) is not type(after):
        yield prefix, before, after
    elif isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            yield from differences(before.get(key), after.get(key), f'{prefix}.{key}')
    elif isinstance(before, list):
        if len(before) != len(after):
            yield f'{prefix}[len]', len(before), len(after)
        for i, (x, y) in enumerate(zip(before, after)):
            yield from differences(x, y, f'{prefix}[{i}]')
    elif before != after:
        yield prefix, before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--compare', help='an earlier --out file to diff against')
    parser.add_argument(
        '--disposable-database',
        action='store_true',
        help='confirm that DATABASE_URL points at a throwaway database',
    )
    args = parser.parse_args()

    if not args.disposable_database or not database_is_marked_disposable():
        print(
            'Refusing to run: this replay writes and deletes rows. Pass '
            '--disposable-database and mark the database with '
            f'COMMENT ON DATABASE "<name>" IS \'{DISPOSABLE_MARKER}\'.',
            file=sys.stderr,
        )
        return 2

    results = replay(args.out)
    if any(r['status'] != 200 or 'errors' in r['body'] for r in results):
        return 1
    if not args.compare:
        return 0

    with open(args.compare) as handle:
        baseline = json.load(handle)
    found = list(differences(baseline, results))
    for path, before, after in found:
        print('DIFF', path, json.dumps(before)[:200], '->', json.dumps(after)[:200])
    print(f'{len(found)} differences from {args.compare}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
