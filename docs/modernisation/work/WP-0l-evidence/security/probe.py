# Security-gate evidence, not shipped code: excluded from lint (lead, WP-0l round 2).
# ruff: noqa
'''WP-0l security gate: live probes against one contract stack.

    uv run --no-project --with requests python /tmp/sec0l/probe.py <label>

Needs CONTRACT_PROJECT and CONTRACT_WEB_PORT. Synthetic @sec0l.invalid accounts
only; refuses any base URL but loopback; never prints a password.
'''

import json
import os
import secrets
import statistics
import subprocess
import sys
import time

import requests

LABEL = sys.argv[1]
PROJECT = os.environ['CONTRACT_PROJECT']
PORT = int(os.environ['CONTRACT_WEB_PORT'])
BASE = f'http://127.0.0.1:{PORT}'
assert BASE.startswith('http://127.0.0.1:')
PASSWORD = secrets.token_hex(16)
WEB = f'{PROJECT}-web-1'
DB = f'{PROJECT}-postgres-1'
DOMAIN = 'sec0l.invalid'
SESSION = requests.Session()


def tag():
    # Starts with a letter so upper() differs from lower().
    return 'q' + secrets.token_hex(3)


def sh(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f'{args[0]} {args[1]} failed: {result.stderr[-400:]}')
    return result.stdout


def sql(query):
    return sh(
        'docker',
        'exec',
        DB,
        'psql',
        '-U',
        'postgres',
        '-d',
        'harmony_demo-local',
        '-tAc',
        query,
    ).strip()


def create_user(username, admin=False):
    args = [
        'docker',
        'exec',
        WEB,
        'python',
        'scripts/create_user.py',
        '-u',
        username,
        '-p',
        PASSWORD,
        '-f',
        'Sec0l',
        '-l',
        'Probe',
    ]
    args += ['-a'] if admin else ['--default_user']
    sh(*args)
    return username


def copy_user(source, username):
    '''A second account stored after `source` (heap order decides ILIKE first()).'''
    sql(
        'insert into "user" (username, password, first_name, last_name, status_id, created) '
        f"select '{username}', password, first_name, last_name, status_id, now() "
        f'from "user" where username = \'{source}\''
    )
    return username


def uid(username):
    return int(sql(f"select id from \"user\" where username = '{username}'"))


def call(user, method, path, body=None):
    return requests.request(
        method,
        BASE + path,
        json=body,
        timeout=120,
        headers={'X-Username': user, 'X-Password': PASSWORD, 'Connection': 'close'},
    )


SPEC = {
    'version': '2023-06-30',
    'items': [],
    'options': {'title': 'Sec0l', 'columnCount': 100},
    'commonSettings': {
        'filterSettings': {
            'enabledCategories': [],
            'excludedTiles': [],
            'items': [],
            'visible': False,
            'enabledFilterHierarchy': [],
        },
        'groupingSettings': {
            'enabledCategories': [],
            'excludedTiles': [],
            'items': [],
            'visible': False,
        },
        'panelAlignment': 'LEFT',
    },
    'legacy': False,
}


def create_dashboard(user, slug):
    response = call(
        user, 'POST', '/api2/dashboard', {'slug': slug, 'specification': SPEC}
    )
    assert response.status_code in (200, 201), (
        slug,
        response.status_code,
        response.text[:200],
    )
    return int(sql(f"select resource_id from dashboard where slug = '{slug.lower()}'"))


def rname(resource_id):
    return sql(f'select name from resource where id = {resource_id}')


def user_acls(resource_id):
    return sql(
        "select coalesce(string_agg(split_part(u.username, '@', 1) || ':' || rr.name, ',' "
        "order by u.username, rr.name), '') "
        'from user_acl a join "user" u on u.id = a.user_id '
        f'join resource_role rr on rr.id = a.resource_role_id where a.resource_id = {resource_id}'
    )


def group_acls(resource_id):
    return sql(
        "select coalesce(string_agg(g.name || ':' || rr.name, ',' order by g.name), '') "
        'from security_group_acl a join security_group g on g.id = a.group_id '
        f'join resource_role rr on rr.id = a.resource_role_id where a.resource_id = {resource_id}'
    )


def rrid(name):
    return int(sql(f"select id from resource_role where name = '{name}'"))


def give_acl(username, role, resource_id):
    sql(
        f'insert into user_acl (user_id, resource_role_id, resource_id) '
        f'values ({uid(username)}, {rrid(role)}, {resource_id})'
    )


def drop_acls(username, resource_id):
    sql(
        f'delete from user_acl where user_id = {uid(username)} and resource_id = {resource_id}'
    )


def make_group(name):
    sql(f"insert into security_group (name) values ('{name}')")
    return int(sql(f"select id from security_group where name = '{name}'"))


def give_group_acl(group_id, role, resource_id):
    sql(
        f'insert into security_group_acl (group_id, resource_role_id, resource_id) '
        f'values ({group_id}, {rrid(role)}, {resource_id})'
    )


def members(group_id):
    return sql(
        "select coalesce(string_agg(split_part(u.username, '@', 1), ',' order by u.username), '') "
        'from security_group_users gu join "user" u on u.id = gu.user_id '
        f'where gu.group_id = {group_id}'
    )


def role_members(role_id):
    return sql(
        "select coalesce(string_agg(split_part(u.username, '@', 1), ',' order by u.username), '') "
        'from user_roles ur join "user" u on u.id = ur.user_id '
        f'where ur.role_id = {role_id}'
    )


def short(text, limit=160):
    return ' '.join(text.split())[:limit]


def row(section, name, outcome):
    print(f'{LABEL} | {section} | {name} | {outcome}', flush=True)


NO_SITEWIDE = {'registeredResourceRole': '', 'unregisteredResourceRole': ''}


def share(user, resource_id, user_roles, group_roles=None):
    return call(
        user,
        'POST',
        f'/api2/resource/{resource_id}/roles',
        {
            'userRoles': user_roles,
            'groupRoles': group_roles or {},
            'sitewideResourceAcl': NO_SITEWIDE,
        },
    )


def acl(role, resource_name, rtype='DASHBOARD'):
    return {
        '$uri': '',
        'resourceRole': {'$uri': '', 'name': role, 'resourceType': rtype},
        'resource': {
            '$uri': '',
            'label': 'x',
            'name': resource_name,
            'resourceType': rtype,
        },
    }


def patch_user(caller, username, acls):
    user_id = uid(username)
    return call(
        caller,
        'PATCH',
        f'/api2/user/{user_id}',
        {
            '$uri': f'/api2/user/{user_id}',
            'username': username,
            'firstName': 'Sec0l',
            'lastName': 'Probe',
            'phoneNumber': '',
            'status': 'active',
            'apiTokens': [],
            'roles': [],
            'groups': [],
            'acls': acls,
        },
    )


T = tag()
admin = create_user(f'admin-{T}@{DOMAIN}', admin=True)
creator = create_user(f'creator-{T}@{DOMAIN}')
accomplice = create_user(f'accomplice-{T}@{DOMAIN}')

# ---------------------------------------------------------------- H and A
for variant in ('_', '%', '.', 'UPPER_'):
    t = tag()
    victim = create_dashboard(admin, f'{t}x{t}')
    slug = f'{t.upper()}_{t.upper()}' if variant == 'UPPER_' else f'{t}{variant}{t}'
    own = create_dashboard(creator, slug)
    row(
        'H',
        f'creator makes slug {slug!r} while {t}x{t} exists',
        f'own resource name={rname(own)} own=[{user_acls(own)}] victim=[{user_acls(victim)}]',
    )

t = tag()
victim = create_dashboard(admin, f'{t}x{t}')
own = create_dashboard(creator, f'{t}_{t}')
# Same starting ACLs on both trees: the creator administers only its own dashboard.
drop_acls(creator, victim)
drop_acls(creator, own)
give_acl(creator, 'dashboard_admin', own)
response = share(
    creator, own, {creator: ['dashboard_admin'], accomplice: ['dashboard_admin']}
)
row(
    'A',
    'non-admin creator shares own a_b (admin to accomplice) while axb exists',
    f'{response.status_code} own=[{user_acls(own)}] victim=[{user_acls(victim)}]',
)

# ---------------------------------------------------------------- B
t = tag()
plain = create_dashboard(admin, f'plain{t}')
dot = create_user(f'{t}.doe@{DOMAIN}')
under = copy_user(dot, f'{t}_doe@{DOMAIN}')
give_acl(dot, 'dashboard_viewer', plain)
give_acl(under, 'dashboard_viewer', plain)
response = share(admin, plain, {admin: ['dashboard_admin'], dot: ['dashboard_viewer']})
row(
    'B',
    'remove x_doe share (x.doe stored first), keep x.doe',
    f'{response.status_code} [{user_acls(plain)}]',
)

g_dot = make_group(f'g.{t}')
g_under = make_group(f'g_{t}')
g_pct_target = make_group(f'gz{t}')
g_pct = make_group(f'g%{t}')
for group_id in (g_dot, g_under, g_pct_target, g_pct):
    give_group_acl(group_id, 'dashboard_viewer', plain)
response = share(
    admin,
    plain,
    {admin: ['dashboard_admin']},
    {f'g.{t}': ['dashboard_viewer'], f'gz{t}': ['dashboard_viewer']},
)
row(
    'B',
    'remove groups g_x and g%x, keep g.x and gzx (look-alikes stored first)',
    f'{response.status_code} [{group_acls(plain)}]',
)

# ---------------------------------------------------------------- C
t = tag()
secret_slug = f'secret{t}abc'
secret = create_dashboard(admin, secret_slug)
uadmin = create_user(f'uadmin-{t}@{DOMAIN}')
role_id = int(
    sql(
        f"insert into role (name, label) values ('uadm_{t}', 'uadm') returning id"
    ).splitlines()[0]
)
sql(
    'insert into role_permissions (role_id, permission_id) '
    f'select {role_id}, p.id from permission p join resource_type rt on rt.id = p.resource_type_id '
    "where (rt.name = 'USER' and p.permission in ('view_resource', 'edit_resource')) "
    "or (rt.name = 'SITE' and p.permission = 'edit_user')"
)
row(
    'C',
    'user admin role permissions',
    sql(
        "select string_agg(rt.name || ':' || p.permission, ',' order by rt.name, p.permission) "
        "from role_permissions rp join permission p on p.id = rp.permission_id "
        f"join resource_type rt on rt.id = p.resource_type_id where rp.role_id = {role_id}"
    ),
)
sql(f'insert into user_roles (user_id, role_id) values ({uid(uadmin)}, {role_id})')
target = create_user(f'tgt-{t}@{DOMAIN}')
for name, payload in (
    ('ACL by pattern secretX%', [acl('dashboard_viewer', f'secret{t}%')]),
    ('ACL by pattern secretX_bc', [acl('dashboard_viewer', f'secret{t}_bc')]),
    ('ACL by exact name', [acl('dashboard_viewer', secret_slug)]),
    ('alert_admin on pattern (type mismatch)', [acl('alert_admin', f'secret{t}%')]),
    ('alert_admin on exact name (type mismatch)', [acl('alert_admin', secret_slug)]),
):
    response = patch_user(uadmin, target, payload)
    row(
        'C',
        f'user admin (no update_users on dashboard): {name}',
        f'{response.status_code} body names it={secret_slug in response.text} body={short(response.text)}',
    )
response = call(
    uadmin,
    'POST',
    '/api/authorization',
    {
        'permission': 'view_resource',
        'resourceType': 'DASHBOARD',
        'resourceName': f'secret{t}%',
    },
)
row(
    'C',
    '/api/authorization by pattern',
    f'{response.status_code} names it={secret_slug in response.text} {short(response.text, 100)}',
)
response = call(
    uadmin,
    'DELETE',
    f'/api2/user/{uid(target)}/roles',
    {
        'roleName': 'dashboard_viewer',
        'resourceType': 'DASHBOARD',
        'resourceName': f'secret{t}%',
    },
)
row(
    'C',
    'legacy DELETE /roles by pattern',
    f'{response.status_code} names it={secret_slug in response.text} {short(response.text, 120)}',
)
logs = subprocess.run(
    ['docker', 'logs', '--since', '10m', WEB], capture_output=True, text=True
)
lines = [
    line for line in (logs.stdout + logs.stderr).splitlines() if secret_slug in line
]
row('C', 'web log lines naming the secret dashboard', f'{len(lines)}')
for line in lines:
    row(
        'C', 'log', short(line[line.find('Refused') if 'Refused' in line else 0 :], 260)
    )

# ---------------------------------------------------------------- D
t = tag()
member = create_user(f'{t}.member@{DOMAIN}')
seed = create_user(f'{t}seed@{DOMAIN}')
group_id = make_group(f'grp{t}')
sql(
    f'insert into security_group_users (group_id, user_id) values ({group_id}, {uid(seed)})'
)
look = f'{t}_member@{DOMAIN}'
response = call(admin, 'PATCH', f'/api2/group/{group_id}/users', [seed, look])
row(
    'D',
    'group PATCH /users [seed, x_member] (only x.member exists)',
    f'{response.status_code} members=[{members(group_id)}]',
)
response = call(admin, 'POST', f'/api2/group/{group_id}/users', f'{t}%member@{DOMAIN}')
row(
    'D',
    'group POST /users x%member',
    f'{response.status_code} members=[{members(group_id)}]',
)
sql(
    f'insert into security_group_users (group_id, user_id) select {group_id}, {uid(member)} '
    f'where not exists (select 1 from security_group_users where group_id = {group_id} and user_id = {uid(member)})'
)
response = call(admin, 'DELETE', f'/api2/group/{group_id}/users', look)
row(
    'D',
    'group DELETE /users x_member (x.member is a member)',
    f'{response.status_code} members=[{members(group_id)}]',
)
role_id = int(
    sql(
        f"insert into role (name, label) values ('r_{t}', 'r') returning id"
    ).splitlines()[0]
)
sql(f'insert into user_roles (user_id, role_id) values ({uid(seed)}, {role_id})')
response = call(admin, 'PATCH', f'/api2/role/{role_id}/users', [seed, look])
row(
    'D',
    'role PATCH /users [seed, x_member]',
    f'{response.status_code} members=[{role_members(role_id)}]',
)
response = call(admin, 'PATCH', f'/api2/role/{role_id}/users', [seed, member.upper()])
row(
    'D',
    'role PATCH /users [seed, X.MEMBER] (case only)',
    f'{response.status_code} members=[{role_members(role_id)}]',
)

# ---------------------------------------------------------------- E
t = tag()
author = create_user(f'{t}.author@{DOMAIN}')
dash = create_dashboard(admin, f'e{t}')
sql(f'update dashboard set author_id = {uid(author)} where resource_id = {dash}')
response = call(
    admin, 'POST', f'/api2/dashboard/{dash}/transfer/username', f'{t}_author@{DOMAIN}'
)
who = sql(
    f'select split_part(u.username, \'@\', 1) from dashboard d join "user" u on u.id = d.author_id where d.resource_id = {dash}'
)
row(
    'E',
    'dashboard item transfer to x_author (only x.author exists)',
    f'{response.status_code} author={who}',
)
response = call(
    admin,
    'POST',
    '/api2/dashboard/transfer/username',
    {'sourceAuthor': f'{t}_author@{DOMAIN}', 'targetAuthor': admin},
)
who = sql(
    f'select split_part(u.username, \'@\', 1) from dashboard d join "user" u on u.id = d.author_id where d.resource_id = {dash}'
)
row(
    'E', 'dashboard bulk transfer from x_author', f'{response.status_code} author={who}'
)
response = call(
    admin,
    'POST',
    '/api2/alert_definitions/transfer/username',
    {'sourceUser': admin, 'targetUser': f'{t}_author@{DOMAIN}'},
)
row('E', 'alert bulk transfer to x_author', f'{response.status_code}')
# Path H through transfer: the new author's admin ACL lands on the transferred dashboard.
t = tag()
victim = create_dashboard(admin, f'{t}x{t}')
moved = create_dashboard(admin, f'{t}_{t}')
heir = create_user(f'heir-{t}@{DOMAIN}')
response = call(
    admin, 'POST', f'/api2/dashboard/{moved}/transfer/username', heir.upper()
)
row(
    'E',
    'transfer a_b to HEIR (case only) while axb exists',
    f'{response.status_code} moved=[{user_acls(moved)}] victim=[{user_acls(victim)}]',
)

# ---------------------------------------------------------------- case pairs and Unicode
t = tag()
upper_twin = create_user(f'Twin{t}@{DOMAIN}')
lower_twin = copy_user(upper_twin, f'twin{t}@{DOMAIN}')
for spelling in (lower_twin, upper_twin, f'TWIN{t}@{DOMAIN}'):
    group_id = make_group(f'pair{t}{secrets.token_hex(2)}')
    response = call(admin, 'POST', f'/api2/group/{group_id}/users', spelling)
    row(
        'Pairs',
        f'group POST /users {spelling.split("@")[0]!r} (Twin and twin exist)',
        f'{response.status_code} members=[{members(group_id)}]',
    )
legit = create_user(f'k{t}@{DOMAIN}')
kelvin = copy_user(legit, f'K{t}@{DOMAIN}')
for spelling, note in (
    (legit, 'legit exact'),
    (f'K{t}@{DOMAIN}', 'ASCII K'),
    (kelvin, 'Kelvin sign exact'),
):
    group_id = make_group(f'kel{t}{secrets.token_hex(2)}')
    response = call(admin, 'POST', f'/api2/group/{group_id}/users', spelling)
    row(
        'Unicode',
        f'group POST /users {note} (k.. and Kelvin-K.. exist)',
        f'{response.status_code} members=[{members(group_id).encode("unicode_escape").decode()}]',
    )

# Exact-name resource twins: any dashboard creator can make one (slug a-b vs a_b).
t = tag()
viewer = create_user(f'viewer-{t}@{DOMAIN}')
victim = create_dashboard(admin, f'v-{t}')
response = share(
    admin, victim, {admin: ['dashboard_admin'], viewer: ['dashboard_viewer']}
)
before_twin = patch_user(admin, viewer, [acl('dashboard_viewer', rname(victim))])
auth_before = call(
    admin,
    'POST',
    '/api/authorization',
    {
        'permission': 'publish_resource',
        'resourceType': 'DASHBOARD',
        'resourceName': f'v-{t}',
    },
)
twin = create_dashboard(creator, f'v_{t}')
after_twin = patch_user(admin, viewer, [acl('dashboard_viewer', rname(victim))])
auth_after = call(
    admin,
    'POST',
    '/api/authorization',
    {
        'permission': 'publish_resource',
        'resourceType': 'DASHBOARD',
        'resourceName': f'v-{t}',
    },
)
reshare = share(
    admin, victim, {admin: ['dashboard_admin'], viewer: ['dashboard_viewer']}
)
row(
    'Twins',
    f'resource names victim={rname(victim)} twin={rname(twin)} (twin made by a default user)',
    '',
)
row(
    'Twins',
    'admin re-saves a viewer of the victim (UI resends ACLs by name)',
    f'before twin {before_twin.status_code}, after twin {after_twin.status_code} {short(after_twin.text, 140)}',
)
row(
    'Twins',
    'admin /api/authorization publish_resource on v-x',
    f'before twin {auth_before.status_code} {short(auth_before.text, 40)}, after twin {auth_after.status_code}',
)
row(
    'Twins',
    'admin shares the victim by its URL after the twin',
    f'{reshare.status_code} victim=[{user_acls(victim)}] twin=[{user_acls(twin)}]',
)

# ---------------------------------------------------------------- legacy /roles
t = tag()
lu = create_user(f'legacy-{t}@{DOMAIN}')
lg = make_group(f'legacy{t}')
for method, path, body in (
    (
        'POST',
        f'/api2/user/{uid(lu)}/roles',
        {'roleName': 'dashboard_viewer', 'resourceType': 'DASHBOARD'},
    ),
    (
        'POST',
        f'/api2/group/{lg}/roles',
        {'roleName': 'dashboard_viewer', 'resourceType': 'DASHBOARD'},
    ),
    (
        'PATCH',
        f'/api2/user/{uid(lu)}/roles',
        {'DASHBOARD': {'sitewideRoles': ['dashboard_viewer'], 'resources': {}}},
    ),
    (
        'PATCH',
        f'/api2/user/{uid(lu)}/roles',
        {'DASHBOARD': {'sitewideRoles': [], 'resources': {'x': []}}},
    ),
    (
        'PATCH',
        f'/api2/group/{lg}/roles',
        {'DASHBOARD': {'sitewideRoles': [], 'resources': {'x': ['dashboard_viewer']}}},
    ),
    ('PATCH', f'/api2/user/{uid(lu)}/roles', {}),
):
    response = call(admin, method, path, body)
    row(
        'Legacy',
        f'{method} {path.split("/")[2]}/<id>/roles {json.dumps(body)[:70]}',
        f'{response.status_code}',
    )
victim = create_dashboard(admin, f'{t}x{t}')
other = create_dashboard(admin, f'{t}_{t}')
give_acl(lu, 'dashboard_viewer', victim)
give_group_acl(lg, 'dashboard_viewer', victim)
response = call(
    admin,
    'DELETE',
    f'/api2/user/{uid(lu)}/roles',
    {
        'roleName': 'dashboard_viewer',
        'resourceType': 'DASHBOARD',
        'resourceName': f'{t}_{t}',
    },
)
row(
    'Legacy',
    'user DELETE /roles naming a_b (ACL is on axb)',
    f'{response.status_code} axb=[{user_acls(victim)}]',
)
response = call(
    admin,
    'DELETE',
    f'/api2/group/{lg}/roles',
    {
        'roleName': 'dashboard_viewer',
        'resourceType': 'DASHBOARD',
        'resourceName': f'{t}_{t}',
    },
)
row(
    'Legacy',
    'group DELETE /roles naming a_b (ACL is on axb)',
    f'{response.status_code} axb=[{group_acls(victim)}]',
)

# ---------------------------------------------------------------- get_resource_by_type_and_name
t = tag()
typed = create_dashboard(admin, f'typed{t}')
for rtype in ('DASHBOARD', 'ALERT', 'dashboard', 'NOPE', None):
    response = call(
        creator,
        'POST',
        '/api/authorization',
        {
            'permission': 'view_resource',
            'resourceType': rtype,
            'resourceName': f'typed{t}',
        },
    )
    row(
        'Type',
        f'creator /api/authorization view_resource {rtype} typed..',
        f'{response.status_code} {short(response.text, 60)}',
    )


# ---------------------------------------------------------------- timing oracle
def sample(fn, n=30):
    times = []
    for _ in range(n):
        start = time.perf_counter()
        status = fn().status_code
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return status, statistics.median(times), times[n // 10], times[-(n // 10) - 1]


t = tag()
hidden = create_dashboard(admin, f'hidden{t}')
twin_a = create_dashboard(admin, f'tw-{t}')
twin_b = create_dashboard(admin, f'tw_{t}')
cases = {
    '403 exists, no update_users': lambda: patch_user(
        uadmin, target, [acl('dashboard_viewer', f'hidden{t}')]
    ),
    '404 no such name': lambda: patch_user(
        uadmin, target, [acl('dashboard_viewer', f'nohidden{t}')]
    ),
    '404 two resources share the name': lambda: patch_user(
        uadmin, target, [acl('dashboard_viewer', f'tw_{t}')]
    ),
    '400 ACL without a name': lambda: patch_user(
        uadmin, target, [acl('dashboard_viewer', '')]
    ),
    'authz 200 exists': lambda: call(
        creator,
        'POST',
        '/api/authorization',
        {
            'permission': 'view_resource',
            'resourceType': 'DASHBOARD',
            'resourceName': f'hidden{t}',
        },
    ),
    'authz 404 missing': lambda: call(
        creator,
        'POST',
        '/api/authorization',
        {
            'permission': 'view_resource',
            'resourceType': 'DASHBOARD',
            'resourceName': f'nohidden{t}',
        },
    ),
}
for _ in range(3):  # warm up every path
    for fn in cases.values():
        fn()
results = {name: [] for name in cases}
for _ in range(30):
    for name, fn in cases.items():
        start = time.perf_counter()
        status = fn().status_code
        results[name].append((status, (time.perf_counter() - start) * 1000))
for name, samples in results.items():
    statuses = sorted({status for status, _ in samples})
    times = sorted(ms for _, ms in samples)
    row(
        'Timing',
        name,
        f'status={statuses} median={statistics.median(times):.1f}ms p10={times[3]:.1f} p90={times[26]:.1f}',
    )


# ---------------------------------------------------------------- audit queries (read-only)
AUTHOR_WITHOUT_ADMIN = (
    "select count(*) from dashboard d where not exists (select 1 from user_acl a "
    "join resource_role rr on rr.id = a.resource_role_id where a.user_id = d.author_id "
    "and a.resource_id = d.resource_id and rr.name = 'dashboard_admin')"
)
ADMIN_VIA_PATTERN = (
    "select count(*) from user_acl a "
    "join resource_role rr on rr.id = a.resource_role_id and rr.name = 'dashboard_admin' "
    "join resource v on v.id = a.resource_id and v.resource_type_id = 2 "
    "join resource o on o.resource_type_id = 2 and o.id <> v.id and v.name ilike o.name "
    "join dashboard od on od.resource_id = o.id and od.author_id = a.user_id "
    "join dashboard vd on vd.resource_id = v.id and vd.author_id <> a.user_id"
)
row('Audit', 'dashboards whose author lacks dashboard_admin', sql(AUTHOR_WITHOUT_ADMIN))
row(
    'Audit',
    'dashboard_admin held via another dashboard name as pattern',
    sql(ADMIN_VIA_PATTERN),
)
