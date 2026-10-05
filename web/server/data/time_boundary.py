# mypy: disallow_untyped_defs=True
from datetime import datetime, timedelta
from typing import Optional, cast
from typing_extensions import TypedDict

from pydruid.utils.filters import Dimension as DimensionFilter
from db.druid.query_client import DruidQueryClient_
from db.druid.util import DRUID_DATE_FORMAT, build_time_interval
from db.druid.datasource import DruidDatasource
from log import LOG

# The ISO8601 format to seconds precision for datetime.
ISO_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'


class TimeBoundaryQuery(TypedDict):
    queryType: str
    dataSource: str


class TimeBoundary(TypedDict):
    maxTime: str
    minTime: str


class TimeBoundaryQueryResult(TypedDict):
    timestamp: str
    result: TimeBoundary


# NOTE: We return the boundary in different formats for the non-filtered and filtered
# versions. The only use of the filtered version is in the field_info api, which should be
# deprecated soon.
class DateTimeInterval(TypedDict):
    max: datetime
    min: datetime


def construct_time_boundary_query(datasource_name: str) -> TimeBoundaryQuery:
    return {'queryType': 'timeBoundary', 'dataSource': datasource_name}


def _datetime_from_iso(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.rsplit('.', 1)[0])


class DataTimeBoundary:
    def __init__(
        self,
        query_client: DruidQueryClient_,
        datasource: DruidDatasource,
        time_boundary: Optional[TimeBoundaryQueryResult] = None,
    ):
        self.datasource = datasource
        self.query_client = query_client
        self.time_boundary = time_boundary

    def load_time_boundary_from_druid(self) -> None:
        """Set time_boundary to the event dict from the time boundary query"""
        LOG.info('Getting time boundary from Druid...')
        result = self.query_client.run_raw_query(
            construct_time_boundary_query(self.datasource.name)
        )
        if len(result) != 1:
            raise AssertionError(f'Result of time boundary query unexpected: {result}')

        self.time_boundary = result[0]
        LOG.info(
            'Done getting time boundary from Druid: %s', self.get_full_time_interval()
        )

    def get_filtered_time_boundary(
        self, query_filter: Optional[DimensionFilter] = None
    ) -> Optional[DateTimeInterval]:
        query = dict(construct_time_boundary_query(self.datasource.name))
        if query_filter:
            query['filter'] = query_filter.build_filter()

        result = self.query_client.run_raw_query(query)
        if len(result) != 1:
            # Bad result for time boundary.
            return None

        return {
            'min': _datetime_from_iso(result[0]['result']['minTime']),
            'max': _datetime_from_iso(result[0]['result']['maxTime']),
        }

    def get_min_data_date(self) -> str:
        """Return a string of format YYYY-MM-DD that was the minimum data date."""
        event = self.get_data_time_boundary()
        min_date = _datetime_from_iso(event['result']['minTime'])
        return min_date.strftime(DRUID_DATE_FORMAT)

    def get_max_data_date(self) -> str:
        """Return a string of format YYYY-MM-DD that was the maximum data date."""
        event = self.get_data_time_boundary()
        max_date = _datetime_from_iso(event['result']['maxTime'])
        return max_date.strftime(DRUID_DATE_FORMAT)

    def get_full_time_interval(self) -> str:
        """Return a string of druid date interval covering the whole range of data
        with [minTime.date, maxTime.date+1day) from the time_boundary query.
        """
        event = self.get_data_time_boundary()
        mintime = _datetime_from_iso(event['result']['minTime'])
        maxtime = _datetime_from_iso(event['result']['maxTime'])
        maxtime = maxtime + timedelta(days=1)
        return build_time_interval(mintime, maxtime)

    def get_data_time_boundary(self) -> TimeBoundaryQueryResult:
        """Return the stored TimeBoundary query result"""
        if self.time_boundary is None:
            self.load_time_boundary_from_druid()

        # NOTE: We have now loaded the time boundary so it is
        # safe to do this cast.
        time_boundary = cast(TimeBoundaryQueryResult, self.time_boundary)
        return time_boundary
