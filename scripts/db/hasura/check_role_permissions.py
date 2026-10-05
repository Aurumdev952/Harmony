#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["graphql-core==3.3.0"]
# ///
'''Check that Hasura's role permissions match the compiled Relay operations.

The Flask proxy sends `x-hasura-role: user` for signed-in users and
`x-hasura-role: anonymous` for public-access visitors. This script introspects
the Relay schema Hasura exposes to each role and validates every operation the
frontend ships (`web/client/**/__generated__/*.graphql.js`) against it:

- every operation must validate for `user`;
- the public-access operations must validate for `anonymous`;
- `anonymous` must have no mutation root;
- every other operation must fail to validate for `anonymous`, except those
  in ANONYMOUS_SUBSET_OPERATIONS, which read only public columns.

With `--print-schema ROLE` it prints that role's schema as SDL instead, which
is what Relay compiles against (`scripts/db/hasura/dev/sync_graphql_schema.sh`).

The admin secret is read from HASURA_ADMIN_SECRET, never from the command line.

Usage: scripts/db/hasura/check_role_permissions.py --hasura_host http://localhost:8088
'''

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from graphql import (
    GraphQLSchema,
    OverlappingFieldsCanBeMergedRule,
    build_client_schema,
    get_introspection_query,
    parse,
    print_schema,
    specified_rules,
    validate,
)

SRC_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_GLOB = 'web/client/**/__generated__/*.graphql.js'
PUBLIC_OPERATIONS = frozenset({'patchDimensionServiceQuery'})
# Reads only dimension and dimension-category ids and names, a subset of what
# the public query returns, so Hasura cannot tell them apart. The proxy only
# checks that the query text starts with the public query, so a signed-out
# visitor can smuggle this one in as a second operation; it reveals nothing new.
ANONYMOUS_SUBSET_OPERATIONS = frozenset({'EditableCalculationQuery'})
ROLES = ('user', 'anonymous')
# Hosts the admin secret may reach over plain http: this machine and the compose
# service.
PLAIN_HTTP_HOSTS = frozenset({'localhost', '127.0.0.1', '::1', 'hasura'})
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


def parse_hasura_host(raw: str) -> str:
    '''Return `raw` without a trailing slash if it is a plain http(s) base URL.

    The admin secret goes to this host, so it must have no credentials, query or
    fragment, and plain http is allowed only for local and compose hosts.
    '''
    host = raw.rstrip('/')
    parts = urllib.parse.urlsplit(host)
    if (
        parts.scheme not in ('http', 'https')
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f'--hasura_host must be a plain http(s) URL, got {raw!r}')
    if parts.scheme == 'http' and parts.hostname not in PLAIN_HTTP_HOSTS:
        raise ValueError(f'--hasura_host must use https for {parts.hostname}')
    return host


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    '''Turn every redirect into an HTTPError, so the admin secret is never re-sent.'''

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def fetch_schema(hasura_host: str, admin_secret: str, role: str) -> GraphQLSchema:
    request = urllib.request.Request(  # noqa: S310  # scheme and host checked in main()
        f'{hasura_host}/v1beta1/relay',
        data=json.dumps({'query': get_introspection_query()}).encode(),
        headers={
            'Content-Type': 'application/json',
            'X-Hasura-Admin-Secret': admin_secret,
            'X-Hasura-Role': role,
        },
    )
    with _OPENER.open(request, timeout=60) as response:
        body = json.load(response)
    if 'errors' in body:
        raise RuntimeError(f'Introspection as {role} failed: {body["errors"]}')
    return build_client_schema(body['data'])


def check(
    operations: dict[str, str],
    user_schema: GraphQLSchema,
    anonymous_schema: GraphQLSchema,
) -> list[str]:
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
        allowed = PUBLIC_OPERATIONS | ANONYMOUS_SUBSET_OPERATIONS
        if name not in allowed and not anonymous_errors:
            failures.append(f'anonymous can run non-public operation {name}')

    missing = (PUBLIC_OPERATIONS | ANONYMOUS_SUBSET_OPERATIONS) - operations.keys()
    failures.extend(f'public operation {name} not found' for name in missing)
    if anonymous_schema.mutation_type is not None:
        failures.append(
            f'anonymous has a mutation root: {anonymous_schema.mutation_type.name}'
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--hasura_host',
        required=True,
        help='base URL of a Hasura the operator runs: https, or http for localhost '
        'and the compose service hasura (sync_graphql_schema.sh passes HASURA_HOST, '
        'default http://localhost:8088)',
    )
    parser.add_argument('--print-schema', choices=ROLES, dest='print_schema_role')
    args = parser.parse_args()
    try:
        hasura_host = parse_hasura_host(args.hasura_host)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    admin_secret = os.environ.get('HASURA_ADMIN_SECRET', '')
    if not admin_secret:
        print('HASURA_ADMIN_SECRET must be set', file=sys.stderr)
        return 2

    if args.print_schema_role:
        schema = fetch_schema(hasura_host, admin_secret, args.print_schema_role)
        print(print_schema(schema))
        return 0

    operations = load_operations(SRC_ROOT)
    failures = check(
        operations,
        *(fetch_schema(hasura_host, admin_secret, role) for role in ROLES),
    )
    for failure in failures:
        print(failure, file=sys.stderr)
    print(f'{len(operations)} operations checked, {len(failures)} failures')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
