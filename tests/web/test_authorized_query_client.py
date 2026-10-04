import pytest

from web.server.routes.views.query_policy import AuthorizedQueryClient


class _RecordingClient:
    def __init__(self):
        self.calls = []

    def run_query(self, query):
        self.calls.append(('run_query', query))

    def run_raw_query(self, query, streaming=False):
        self.calls.append(('run_raw_query', query))
        return []


def test_user_scoped_client_has_no_unfiltered_raw_path():
    system_client = _RecordingClient()
    user_client = AuthorizedQueryClient(system_client)

    with pytest.raises(AttributeError):
        user_client.run_raw_query({'queryType': 'timeseries', 'dataSource': 'x'})

    assert not system_client.calls
