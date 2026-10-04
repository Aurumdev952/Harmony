from web.server.routes.views.query_policy import AuthorizedQueryClient


def test_user_scoped_client_offers_no_unfiltered_raw_query():
    # SEC-4: a raw Druid dict cannot carry the caller's query policy, so the
    # user-scoped client must not expose one. Policy application on run_query is
    # covered by the authorisation suite (tests/authz, WP-2b).
    assert not hasattr(AuthorizedQueryClient, 'run_raw_query')
