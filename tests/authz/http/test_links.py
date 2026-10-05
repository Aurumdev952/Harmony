'''Where mailed links point (WP-0k INV-3 rows L-1 to L-5).

A reset, invite, access-granted, new-dashboard or share link carries a token or
leads a recipient to sign in, so a link built from the request (its Host, its
proxy headers or its script root) let a caller send someone else's token to a
host of its choosing. WP-0k builds every mailed link on the configured origin,
`DEPLOYMENT_BASE_URL`, and takes nothing but a known locale and a `#h=` session
hash from a caller's link.

Each flow runs under three forgeries: a Host header, `X-Forwarded-*` headers,
and a `SCRIPT_NAME` header with the request path prefixed by it (gunicorn takes
the script root from that header). The stack's forwarder passes requests to
gunicorn unchanged, as when gunicorn is reachable without the stock
nginx-proxy (WP-0k unit 1).
Before WP-0k (integration f5d5993) the links took the request's scheme, host
and script root: `http://attacker.invalid/...`, or the stack's own
`http://127.0.0.1:<port>/@attacker.invalid/...`. After: every link is on
`https://harmony_demo.zenysis.com`.
'''

from __future__ import annotations

import os
import secrets

import pytest

from tests.authz.http.stack import TIMEOUT_SECONDS, USER_DOMAIN, new_session

# config/harmony_demo/general.py DEPLOYMENT_BASE_URL, the deployment the stack runs.
ORIGIN = 'https://harmony_demo.zenysis.com'
ATTACKER = 'attacker.invalid'
FORGERIES = {
    'host': ({'Host': ATTACKER}, ''),
    'x-forwarded': (
        {
            'X-Forwarded-Host': ATTACKER,
            'X-Forwarded-Proto': 'http',
            'X-Forwarded-Port': '80',
            'X-Forwarded-Prefix': f'/{ATTACKER}',
        },
        '',
    ),
    'script-name': ({'SCRIPT_NAME': f'@{ATTACKER}'}, f'/@{ATTACKER}'),
}


def _post(stack, session, path, body, forgery):
    headers, prefix = FORGERIES[forgery]
    return session.post(
        f'{stack.base_url}{prefix}{path}',
        json=body,
        headers=headers,
        allow_redirects=False,
        timeout=TIMEOUT_SECONDS,
    )


def _mailed_links(stack) -> list:
    '''The web links of every message mailed since `clear_mail`, oldest first.'''
    return [
        [link for link in message['links'] if link.startswith(('http', 'javascript'))]
        for message in stack.mail()
    ]


def _account(stack, local_part):
    username = f'{local_part}@{USER_DOMAIN}'
    return username, stack.create_account(username, secrets.token_urlsafe(18))


def _token_link(links, path):
    '''The one link, with its token checked to be present and then elided.'''
    assert len(links) == 1 and len(links[0]) == 1, links
    link = links[0][0]
    prefix = f'{ORIGIN}{path}?token='
    assert link.startswith(prefix) and len(link) > len(prefix), link
    return prefix


@pytest.fixture(name='mailbox')
def fixture_mailbox(stack):
    stack.clear_mail()
    return stack


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_forgot_password_link_is_on_the_configured_origin(mailbox, forgery):
    '''Row L-1: `POST /api2/authentication/forgot_password`, anonymous.'''
    username, _ = _account(mailbox, f'link-forgot-{forgery}')

    response = _post(
        mailbox,
        new_session(),
        '/api2/authentication/forgot_password',
        {'email': username},
        forgery,
    )

    assert response.status_code == 200, response.text[:300]
    _token_link(_mailed_links(mailbox), '/user/reset-password')


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_admin_reset_link_is_on_the_configured_origin(mailbox, forgery):
    '''Row L-1: the admin's `POST /api2/user/<id>/reset_password`.'''
    _, uri = _account(mailbox, f'link-reset-{forgery}')

    response = _post(
        mailbox, mailbox.admin_bearer(), f'{uri}/reset_password', None, forgery
    )

    assert response.status_code < 300, response.text[:300]
    _token_link(_mailed_links(mailbox), '/user/reset-password')


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_invite_link_is_on_the_configured_origin(mailbox, forgery):
    '''Row L-2: `POST /api2/user/invite`.'''
    response = _post(
        mailbox,
        mailbox.admin_bearer(),
        '/api2/user/invite',
        [{'email': f'link-invitee-{forgery}@{USER_DOMAIN}', 'name': 'Authz Invitee'}],
        forgery,
    )

    assert response.status_code == 200, response.text[:300]
    for invitee in response.json():
        mailbox.created_users.add(invitee['$uri'])
    _token_link(_mailed_links(mailbox), '/zen/register')


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_new_dashboard_link_is_on_the_configured_origin(mailbox, forgery):
    '''Row L-4: the email `POST /api2/dashboard` sends its creator.'''
    headers, prefix = FORGERIES[forgery]
    slug = f'link_new_{forgery.replace("-", "_")}'

    mailbox.create_dashboard(slug, headers, prefix)

    assert _mailed_links(mailbox) == [
        [f'{ORIGIN}/dashboard/{slug}?source=new_dashboard_email']
    ]


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_access_granted_link_is_the_dashboards_slug_on_the_configured_origin(
    mailbox, forgery
):
    '''Row L-3: the email `POST /api2/resource/<id>/roles` sends a user granted
    a dashboard role. The dashboard's resource is renamed so that its name and
    slug differ: before WP-0k the link named the resource.'''
    slug = f'link_granted_{forgery.replace("-", "_")}'
    dashboard = mailbox.create_dashboard(slug)
    resource = dashboard['resource']
    mailbox.sql(
        'UPDATE resource SET name = :\'name\' WHERE id = :\'id\';',
        name=f'resource-name-{forgery}',
        id=resource.rsplit('/', 1)[1],
    )
    grantee, _ = _account(mailbox, f'link-grantee-{forgery}')
    mailbox.clear_mail()

    response = _post(
        mailbox,
        mailbox.admin_bearer(),
        f'{resource}/roles',
        {
            'userRoles': {
                dashboard['authorUsername']: ['dashboard_admin'],
                grantee: ['dashboard_viewer'],
            },
            'groupRoles': {},
            'sitewideResourceAcl': {
                'registeredResourceRole': '',
                'unregisteredResourceRole': '',
            },
        },
        forgery,
    )

    assert response.status_code == 204, response.text[:300]
    assert _mailed_links(mailbox) == [
        [f'{ORIGIN}/dashboard/{slug}?source=dashboard_permission_email']
    ]


SHARED_SOURCE = 'source=shared_dashboard_email'


@pytest.mark.parametrize(
    ('dashboard_url', 'expected'),
    [
        ('https://attacker.invalid/phish', '/dashboard/{slug}?' + SHARED_SOURCE),
        ('javascript:alert(document.domain)', '/dashboard/{slug}?' + SHARED_SOURCE),
        (
            'https://attacker.invalid/xx/dashboard/other#h=0123abcd',
            '/dashboard/{slug}?' + SHARED_SOURCE + '#h=0123abcd',
        ),
        (
            'https://attacker.invalid/fr/dashboard/other#h=0123abcd',
            '/fr/dashboard/{slug}?' + SHARED_SOURCE + '#h=0123abcd',
        ),
    ],
    ids=['hostile-origin', 'javascript', 'unknown-locale', 'known-locale'],
)
@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_shared_dashboard_link_is_the_dashboards_page_on_the_configured_origin(
    mailbox, forgery, dashboard_url, expected
):
    '''Row L-5: `POST /api2/dashboard/<id>/share_via_email`. The caller's
    `dashboardUrl` contributes only a locale Harmony has and the `#h=` hash.
    Before WP-0k it was mailed as the link, whatever it was.'''
    slug = 'link_shared'
    found = mailbox.admin_json('GET', f'/api2/dashboard?where={{"slug": "{slug}"}}')
    dashboard = found[0] if found else mailbox.create_dashboard(slug)
    mailbox.clear_mail()

    response = _post(
        mailbox,
        mailbox.admin_bearer(),
        f'{dashboard["$uri"]}/share_via_email',
        {
            'recipients': [f'link-share-recipient@{USER_DOMAIN}'],
            'message': 'Authz message',
            'subject': 'Authz subject',
            'sender': dashboard['authorUsername'],
            'shouldAttachPdf': False,
            'shouldEmbedImage': False,
            'dashboardUrl': dashboard_url,
            'useRecipientQueryPolicy': False,
            'useSingleEmailThread': False,
        },
        forgery,
    )

    assert response.status_code == 200, response.text[:300]
    assert _mailed_links(mailbox) == [[ORIGIN + expected.format(slug=slug)]]


@pytest.mark.parametrize('forgery', sorted(FORGERIES))
def test_shared_analysis_link_is_the_advanced_query_page_on_the_configured_origin(
    mailbox, forgery
):
    '''Row L-5: `POST /api2/share/email` with a hostile `queryUrl`.'''
    response = _post(
        mailbox,
        mailbox.admin_bearer(),
        '/api2/share/email',
        {
            'attachments': [],
            'imageUrl': '',
            'isPreview': False,
            'message': 'Authz message',
            'queryUrl': 'https://attacker.invalid/advanced-query#h=0123abcd',
            'sender': os.environ['AUTHZ_ADMIN_USERNAME'],
            'subject': 'Authz subject',
            'recipients': [f'link-share-recipient@{USER_DOMAIN}'],
        },
        forgery,
    )

    assert response.status_code == 200, response.text[:300]
    assert _mailed_links(mailbox) == [[f'{ORIGIN}/advanced-query#h=0123abcd']]
