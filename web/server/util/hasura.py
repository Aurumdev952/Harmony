'''Session headers the Flask proxy sends to Hasura.

Hasura trusts `X-Hasura-Role` and `X-Hasura-User-Id` only when the admin secret
accompanies them. The roles are defined in
`graphql/hasura/metadata/versions/latest/tables.yaml`:
- `user` covers the tables and operations the signed-in UI needs;
- `anonymous` can read the dimension tables behind the public-access query.
'''

HASURA_ROLE_USER = 'user'
HASURA_ROLE_ANONYMOUS = 'anonymous'


def build_hasura_headers(user, admin_secret: str) -> dict:
    headers = {'X-Hasura-Admin-Secret': admin_secret}
    if user.is_authenticated:
        headers['X-Hasura-Role'] = HASURA_ROLE_USER
        headers['X-Hasura-User-Id'] = str(user.id)
    else:
        headers['X-Hasura-Role'] = HASURA_ROLE_ANONYMOUS
    return headers
