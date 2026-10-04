import json
import re

from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound

from db.druid.query_builder import GroupByQueryBuilder
from db.druid.util import EmptyFilter
from web.server.routes.views.query_policy import (
    and_policy_filter,
    caller_policy_filter,
)
from web.server.util.indicators import get_indicator_by_id

ISO_DATETIME_FORMAT = '%Y-%m-%d'
MAX_FIELD_IDS_PER_REQUEST = 20


# TODO - A parting gift from Vedant. Please make this a Potion API.
class FieldSummary:
    def __init__(
        self,
        field_id,
        count=0,
        start_date=None,
        end_date=None,
        formula=None,
        human_readable_formula=None,
    ):
        self.field_id = field_id
        self.count = count
        self.start_date = start_date
        self.end_date = end_date
        self.formula = formula
        self.human_readable_formula = human_readable_formula

    def to_json(self):
        # JSON consumed by the frontend is camelCased.
        return {
            'startDate': (
                self.start_date.strftime(ISO_DATETIME_FORMAT)
                if self.start_date
                else None
            ),
            'endDate': (
                self.end_date.strftime(ISO_DATETIME_FORMAT) if self.end_date else None
            ),
            'count': self.count,
            'formula': self.formula,
            'humanReadableFormulaHtml': self.human_readable_formula,
        }

    def __str__(self):
        return json.dumps(self.to_json(), indent=2)


def get_field_summaries(field_ids):
    '''Summaries of configured fields. Counts and dates cover only the rows the
    caller's query policy allows; formulas are configuration and always returned.
    '''
    if len(field_ids) > MAX_FIELD_IDS_PER_REQUEST:
        raise BadRequest(
            description=f'At most {MAX_FIELD_IDS_PER_REQUEST} field ids per request.'
        )
    configured_field_ids = current_app.zen_config.indicators.ID_LOOKUP
    if not all(field_id in configured_field_ids for field_id in field_ids):
        raise NotFound(description='Unknown field id.')

    field_rows = _FieldRows(caller_policy_filter())
    summaries = {}
    for field_id in field_ids:
        formula = _indicator_formula(field_id)
        summaries[field_id] = FieldSummary(
            field_id,
            *field_rows.count_and_range(field_id),
            formula=formula,
            human_readable_formula=_human_readable_formula_html(formula),
        )
    return summaries


def _indicator_formula(field_id):
    return get_indicator_by_id(field_id, {'formula'}).get('formula')


def _human_readable_formula_html(formula):
    if not formula:
        return None
    matches = re.findall(r'\w+', formula)

    if not matches:
        return None

    ret = formula[:]
    ret = (
        ret.replace(' ', '')
        .replace('+', ' + ')
        .replace('-', ' - ')
        .replace('/', ' / ')
        .replace('*', ' * ')
    )
    for constit_field_id in set(matches):
        ind = get_indicator_by_id(constit_field_id)
        if ind:
            ret = ret.replace(constit_field_id, f"<span>{ind['text']}</span>")
    return ret


class _FieldRows:
    '''Row count and date range of a field within one caller's query policy.'''

    def __init__(self, policy_filter):
        druid_context = current_app.druid_context
        self.policy_filter = policy_filter
        self.time_boundary_lookup = druid_context.data_time_boundary
        self.row_count_lookup = druid_context.row_count_lookup
        self.interval = self.time_boundary_lookup.get_full_time_interval()
        self.get_calculation_for_fields = (
            current_app.zen_config.aggregation_rules.get_calculation_for_fields
        )

    def count_and_range(self, field_id):
        '''(count, first date, last date), or (0, None, None) with no rows.'''
        # Simulate building a query so we can access the query filter this field
        # would normally use.
        # NOTE: Setting granularity to month so that type=STOCK
        # aggregations are counted properly. This fails for
        # stock_granularity!=month, but there are very few of those.
        field_filter = GroupByQueryBuilder(
            '',
            'month',
            [],
            [self.interval],
            self.get_calculation_for_fields([field_id]),
        ).query_filter
        # With no filter (missing constituents, or an unfiltered aggregation) Druid
        # would count every row the caller can see, not this field's rows.
        if field_filter is None or isinstance(field_filter, EmptyFilter):
            return 0, None, None

        # The row-count cache is process-wide and keyed by field id, so only callers
        # without a policy may share it.
        query_filter, row_count_cache_key = field_filter, field_id
        if self.policy_filter is not None:
            query_filter = and_policy_filter(field_filter, self.policy_filter)
            row_count_cache_key = None

        # TODO: These values will be underreported for time interval
        # aggregations. Fix this.
        time_boundary = self.time_boundary_lookup.get_filtered_time_boundary(
            query_filter
        )
        if not time_boundary:
            return 0, None, None
        count = self.row_count_lookup.get_row_count(query_filter, row_count_cache_key)
        if not count:
            return 0, None, None
        return count, time_boundary['min'], time_boundary['max']
