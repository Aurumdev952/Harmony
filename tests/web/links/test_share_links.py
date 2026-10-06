"""WP-0k: share-by-email links point at this deployment's own page.

Before WP-0k, `share_via_email` mailed the caller's free-form `dashboardUrl`,
and `/api2/share/email` the caller's `queryUrl`, as the email's link. Only the
locale and the `#h=` session hash are taken from the caller's link now.
"""

from types import SimpleNamespace

import pytest
from flask import g

from tests.web.links.support import INVITER, ORIGIN, mailed_links, request_as
from web.server.api.share_analysis_api_models import ShareAnalysisResource
from web.server.routes.views.dashboard import send_email

DASHBOARD = SimpleNamespace(slug='malaria-overview')
SHARED = '?source=shared_dashboard_email'
PAGE = f'{ORIGIN}/dashboard/malaria-overview'

# (caller's link, mailed link). The source parameter goes before the fragment,
# where the page can read it and does not take it for part of the session hash.
DASHBOARD_LINKS = [
    (None, f'{PAGE}{SHARED}'),
    ('', f'{PAGE}{SHARED}'),
    (f'{PAGE}#h=a1b2c3', f'{PAGE}{SHARED}#h=a1b2c3'),
    (
        f'{ORIGIN}/fr/dashboard/malaria-overview#h=a1b2c3',
        f'{ORIGIN}/fr/dashboard/malaria-overview{SHARED}#h=a1b2c3',
    ),
    # A page opened from a shared link, shared again with its current filters.
    (f'{PAGE}#h=a1b2c3#h=d4e5f6', f'{PAGE}{SHARED}#h=d4e5f6'),
    ('https://attacker.invalid/dashboard/malaria-overview', f'{PAGE}{SHARED}'),
    (
        'https://attacker.invalid/fr/dashboard/elsewhere#h=a1b2c3',
        f'{ORIGIN}/fr/dashboard/malaria-overview{SHARED}#h=a1b2c3',
    ),
    # Only Harmony's locales: any other first path segment is dropped.
    (f'{ORIGIN}/api2/dashboard/malaria-overview', f'{PAGE}{SHARED}'),
    (f'{ORIGIN}/%40attacker.invalid/dashboard/malaria-overview', f'{PAGE}{SHARED}'),
    ('http://[::1/dashboard/x#h=a1b2c3', f'{PAGE}{SHARED}'),
    ('https://harmony.example.org@attacker.invalid/dashboard/x', f'{PAGE}{SHARED}'),
    ('//attacker.invalid/dashboard/malaria-overview', f'{PAGE}{SHARED}'),
    ('javascript:alert(1)//', f'{PAGE}{SHARED}'),
    (f'{ORIGIN}/advanced-query#h=a1b2c3', f'{PAGE}{SHARED}#h=a1b2c3'),
    (f'{PAGE}#h="><a href="https://attacker.invalid/">', f'{PAGE}{SHARED}'),
    (f'{PAGE}#h=a1b2c3/../../x', f'{PAGE}{SHARED}'),
]


@pytest.mark.parametrize(
    'dashboard_url, expected', DASHBOARD_LINKS, ids=[str(c[0]) for c in DASHBOARD_LINKS]
)
def test_dashboard_share_links_the_dashboard_page(app, mailer, dashboard_url, expected):
    with request_as(app, {'HTTP_HOST': 'attacker.invalid'}, username=INVITER.username):
        send_email(
            INVITER,
            DASHBOARD,
            ['viewer@harmony.example.org'],
            'A dashboard for you',
            'Malaria overview',
            INVITER.username,
            dashboard_url=dashboard_url,
            should_attach_pdf=False,
            should_embed_image=False,
        )

    [message] = mailer.messages
    assert mailed_links(message, '/') == {expected}


QUERY = f'{ORIGIN}/advanced-query'
QUERY_LINKS = [
    (f'{QUERY}#h=d41d8cd9', f'{QUERY}#h=d41d8cd9'),
    (
        f'{ORIGIN}/fr/advanced-query#h=d41d8cd9',
        f'{ORIGIN}/fr/advanced-query#h=d41d8cd9',
    ),
    ('https://attacker.invalid/advanced-query#h=d41d8cd9', f'{QUERY}#h=d41d8cd9'),
    ('https://attacker.invalid/phish', QUERY),
    (f'{QUERY}#h="><img src=x>', QUERY),
]


@pytest.mark.parametrize(
    'query_url, expected', QUERY_LINKS, ids=[c[0] for c in QUERY_LINKS]
)
def test_analysis_share_links_the_query_page(app, mailer, query_url, expected):
    share_by_email = ShareAnalysisResource.share_by_email.view_func
    with request_as(app, {'HTTP_HOST': 'attacker.invalid'}, username=INVITER.username):
        g.identity = SimpleNamespace(id=INVITER.id)
        share_by_email(
            None,
            subject='An analysis',
            sender=INVITER.username,
            message='Have a look',
            image_url=None,
            recipients=['viewer@harmony.example.org'],
            attachments=[],
            query_url=query_url,
        )

    [message] = mailer.messages
    assert mailed_links(message, '/') == {expected}
