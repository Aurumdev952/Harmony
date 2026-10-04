#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["graphql-core>=3.2,<4"]
# ///
'''Check that Hasura's role permissions cover every compiled Relay operation.

The Flask proxy sends `x-hasura-role: user` for signed-in users and
`x-hasura-role: anonymous` for public-access visitors. This script introspects
the Relay schema Hasura exposes to each role and validates every operation the
frontend ships (`web/client/**/__generated__/*.graphql.js`) against it:

- every operation must validate for `user`;
- the public-access operations must validate for `anonymous`;
- no mutation may validate for `anonymous`.

Usage: HASURA_ADMIN_SECRET=... scripts/db/hasura/check_role_permissions.py \
    --hasura_host http://localhost:8088
'''
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from graphql import (
    OperationDefinitionNode,
    OperationType,
    OverlappingFieldsCanBeMergedRule,
    build_client_schema,
    get_introspection_query,
    parse,
    specified_rules,
    validate,
)

SRC_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_GLOB = 'web/client/**/__generated__/*.graphql.js'
PUBLIC_OPERATIONS = frozenset({'patchDimensionServiceQuery'})
TEXT_PATTERN = re.compile(r'"text": ("(?:[^"\\]|\\.)*")')
# Relay documents select one root field twice under mutually exclusive
# @include/@skip, which Hasura runs but the spec's field-merge rule rejects.
RULES = [
    rule for rule in specified_rules if rule is not OverlappingFieldsCanBeMergedRule
]


def load_operations(src_root: Path) -> dict[str, str]:
    operations = {}
    for artifact in sorted(src_root.glob(ARTIFACT_GLOB)):
        for literal in TEXT_PATTERN.findall(artifact.read_text()):
            text = json.loads(literal)
            name = parse(text).definitions[0].name.value
            operations[name] = text
    return operations


def fetch_schema(hasura_host: str, admin_secret: str, role: str):
    request = urllib.request.Request(
        f'{hasura_host}/v1beta1/relay',
        data=json.dumps({'query': get_introspection_query()}).encode(),
        headers={
            'Content-Type': 'application/json',
            'X-Hasura-Admin-Secret': admin_secret,
            'X-Hasura-Role': role,
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    if 'errors' in body:
        raise RuntimeError(f'Introspection as {role} failed: {body["errors"]}')
    return build_client_schema(body['data'])


def is_mutation(text: str) -> bool:
    return any(
        isinstance(definition, OperationDefinitionNode)
        and definition.operation == OperationType.MUTATION
        for definition in parse(text).definitions
    )


def check(operations: dict[str, str], user_schema, anonymous_schema) -> list[str]:
    failures = []
    for name, text in operations.items():
        document = parse(text)
        errors = validate(user_schema, document, RULES)
        if errors:
            failures.append(f'user cannot run {name}: {errors[0].message}')

        anonymous_errors = validate(anonymous_schema, document, RULES)
        if name in PUBLIC_OPERATIONS and anonymous_errors:
            failures.append(
                f'anonymous cannot run {name}: {anonymous_errors[0].message}'
            )
        if is_mutation(text) and not anonymous_errors:
            failures.append(f'anonymous can run mutation {name}')

    missing = PUBLIC_OPERATIONS - operations.keys()
    failures.extend(f'public operation {name} not found' for name in missing)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hasura_host', required=True)
    args = parser.parse_args()
    admin_secret = os.environ.get('HASURA_ADMIN_SECRET', '')
    if not admin_secret:
        print('HASURA_ADMIN_SECRET must be set', file=sys.stderr)
        return 2

    operations = load_operations(SRC_ROOT)
    failures = check(
        operations,
        fetch_schema(args.hasura_host, admin_secret, 'user'),
        fetch_schema(args.hasura_host, admin_secret, 'anonymous'),
    )
    for failure in failures:
        print(failure, file=sys.stderr)
    print(f'{len(operations)} operations checked, {len(failures)} failures')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
