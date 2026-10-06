'''This module is responsible for managing CRUD requests against the Query Policy API and also for
converting query policies into Druid Filters which are used to restrict query access.
'''

import json
from collections import defaultdict
from functools import wraps
from datetime import datetime

from flask import g, current_app
from pydruid.utils.filters import Dimension, Filter

from db.druid.util import EmptyFilter
from models.python.permissions import QueryNeed
from web.server.security.permissions import (
    SuperUserPermission,
    is_public_dashboard_user,
)

# pylint: disable=C0103
MINIMUM_DATETIME = datetime(1800, 1, 1)
MAXIMUM_DATETIME = datetime(2200, 12, 31)
ALL_VALUES_SYMBOL = '<<ALL>>'
ALL_VALUES_LIST = [ALL_VALUES_SYMBOL]

AND_FILTER_SYMBOL = 'and'
OR_FILTER_SYMBOL = 'or'
NOT_FILTER_SYMBOL = 'not'
IN_FILTER_SYMBOL = 'in'
SELECTOR_FILTER_SYMBOL = 'selector'
REGEX_FILTER_SYMBOL = 'regex'
COLUMN_COMPARATOR_FILTER_SYMBOL = 'columnComparison'

DRUID_FILTER_TYPES = {
    AND_FILTER_SYMBOL,
    OR_FILTER_SYMBOL,
    NOT_FILTER_SYMBOL,
    IN_FILTER_SYMBOL,
    SELECTOR_FILTER_SYMBOL,
    REGEX_FILTER_SYMBOL,
    COLUMN_COMPARATOR_FILTER_SYMBOL,
}

DRUID_COMPOSITE_FILTER_TYPES = {AND_FILTER_SYMBOL, OR_FILTER_SYMBOL, NOT_FILTER_SYMBOL}

# The following are key names used for dimension to QueryNeed maps
COMPLEX = 'complex'
SIMPLE = 'simple'
HIERARCHICAL = 'hierarchical'

# NOTE: We explicitly filter for this value for a dimension that has not
# been given a value due to fields with aggregate values in which case that
# dimension has no value. Therefore we cannot filter for an empty string.
NO_FILTER_VAL = '__NO_VAL__'


def apply_authorization_filters():
    '''A decorator that applies filters to the run query method of a DruidQueryClient that
    restricts the result dataframe to match whatever data the current user is authorized to view.
    '''

    def filter_query(run_query):
        @wraps(run_query)
        def filter_query_inner(self, query):
            policy_filter = caller_policy_filter()
            if policy_filter is not None:
                query.query_filter = and_policy_filter(
                    query.query_filter, policy_filter
                )
                # A query-modifying aggregation (ExactUniqueCount) rebuilds its
                # inner query from dimension_filter and drops query_filter.
                if hasattr(query, 'dimension_filter'):
                    query.dimension_filter = and_policy_filter(
                        query.dimension_filter, policy_filter
                    )
            return run_query(self, query)

        return filter_query_inner

    return filter_query


def caller_policy_filter():
    '''The current caller's query policy as a Druid filter, or None when no policy
    limits what they see.

    Site administrators and, when public access is on, unregistered users have no
    policy. Every other user sees only what their Query Policies allow.
    NOTE: an API token issued to a site administrator keeps the administrator role,
    so the token's own query_needs do not narrow it here.
    '''
    if SuperUserPermission().can() or is_public_dashboard_user():
        return None

    authorization_filter = _construct_authorization_filter(g.identity)
    if not authorization_filter or isinstance(authorization_filter, EmptyFilter):
        return None
    return authorization_filter


def and_policy_filter(query_filter, policy_filter):
    '''The query filter ANDed with a policy filter, as a new filter.'''
    # EmptyFilter builds as null, and Druid rejects a null AND operand.
    if query_filter is None or isinstance(query_filter, EmptyFilter):
        return policy_filter
    # Not `&`: pydruid appends into an existing "and" filter in place.
    return Filter(type=AND_FILTER_SYMBOL, fields=[query_filter, policy_filter])


def enumerate_query_needs(user_identity=None):
    user_identity = user_identity or g.identity

    query_needs = [
        need for need in user_identity.provides if isinstance(need, QueryNeed)
    ]

    return query_needs


def _categorize_query_needs_type(query_needs):
    '''Categorizes QueryNeeds into simple and complex needs - simple is a single
    filter in a QueryNeed.
    '''
    category_map = {COMPLEX: [], SIMPLE: [], HIERARCHICAL: []}
    for query_need in query_needs:
        if len(query_need.dimension_filters) > 1:
            category = COMPLEX
        else:
            category = SIMPLE
            hierarchical_dimensions = (
                current_app.zen_config.datatypes.HIERARCHICAL_DIMENSIONS
            )
            if any(
                f.dimension_name
                for f in query_need.dimension_filters
                if f.dimension_name in hierarchical_dimensions
            ):
                category = HIERARCHICAL
        category_map[category].append(query_need)
    return category_map


def _construct_authorization_filter(user_identity):
    '''Returns Druid filter that encodes the restrictions a user has. There are
    two components to this computation:
    1) Simple Filters - Each of these QueryPolicies represents a single
        dimension, and are additive: For the same dimension, if a user has
        distinct Policy A and Policy B, they are merged together as Policy (A OR
        B). For different dimensions, the resultant policy is ANDed together. In
        essence, stacked simple filters will only increase the amount of data
        able to be accessed.
    2) Complex Filters - Each QueryPolicy acts as a distinct unit, a user
        receives access to exactly the ANDed filter of the compoennts in that
        policy.
    3) Hierarchical Filters - These are to be SIMPLE filters of dimensions that
        have a hierarchical relationship with each other. The use case here is
        locations: While for SIMPLE Filters, different dimensions are ANDed
        together, we want hierarchical dimensions to be ORed.

    All Simple Filters are compiled together to form one cohesive filter.This
    and all Complex Filters are then ORed together. Hierarchical filters are then
    ANDed to form a full_filter.
    authorization filter.
    '''
    simple_map, hierarchical_map, complex_maps = _policy_filter_maps(
        enumerate_query_needs(user_identity)
    )
    simple_and_hierarchical_filters = _and_simple_and_hierarchical_filters(
        simple_map, hierarchical_map
    )
    return _or_all_filters(simple_and_hierarchical_filters, complex_maps)


def _policy_filter_maps(query_needs):
    '''The simple, hierarchical and per-complex-need dimension maps that
    `_construct_authorization_filter` builds a policy filter from.
    '''
    category_map = _categorize_query_needs_type(query_needs)
    simple_map = _categorize_query_needs(category_map[SIMPLE])
    hierarchical_map = _categorize_query_needs(
        category_map[HIERARCHICAL], dimensions_type=HIERARCHICAL
    )
    complex_maps = [
        _categorize_query_needs([query_need]) for query_need in category_map[COMPLEX]
    ]
    return simple_map, hierarchical_map, complex_maps


def canonical_policy(query_needs):
    '''The maps a policy filter is built from, as JSON-ready values that do not
    depend on set order: query needs with equal canonical policies build equal
    filters.
    '''

    def canonical(dimension_map):
        return {
            dimension: {'all_values': True}
            if values['all_values']
            else {
                'include': sorted(values['include'], key=str),
                'exclude': sorted(values['exclude'], key=str),
            }
            for dimension, values in dimension_map.items()
        }

    simple_map, hierarchical_map, complex_maps = _policy_filter_maps(query_needs)
    # Any all-values hierarchical dimension lifts the whole hierarchical filter.
    hierarchical = (
        'all_values'
        if any(values['all_values'] for values in hierarchical_map.values())
        else canonical(hierarchical_map)
    )
    return {
        'simple': canonical(simple_map),
        'hierarchical': hierarchical,
        'complex': sorted(
            (canonical(dimension_map) for dimension_map in complex_maps),
            key=lambda value: json.dumps(value, sort_keys=True),
        ),
    }


def _and_simple_and_hierarchical_filters(simple_value_map, hierarchical_value_map=None):
    _filter = _construct_single_filter(simple_value_map)
    if hierarchical_value_map:
        _filter &= _construct_hierarchical_filter(hierarchical_value_map)
    return _filter


def _or_all_filters(full_filter, dimension_value_maps):
    '''Returns a Druid filter that comprises an OR across simple and complex Druid filters
    which is constructed for each individual dimension to filter map that is
    passed in.
    '''
    for dimension_value_map in dimension_value_maps:
        full_filter |= _construct_single_filter(dimension_value_map)
    return full_filter


def get_empty_filter_map():
    return defaultdict(
        lambda: {'include': set(), 'exclude': set(), 'all_values': False}
    )


def populate_filter_map_with_need(filter_map, query_need):
    '''Populates a dimension to filter map from the each individual filter from
    a QueryNeed.
    '''
    for (
        dimension_name,
        dimension_filter,
    ) in query_need.dimension_to_filter_mapping.items():
        if dimension_name in current_app.zen_config.filters.AUTHORIZABLE_DIMENSIONS:
            entry = filter_map[dimension_name]
            entry['include'].update(dimension_filter.include_values)
            entry['exclude'].update(dimension_filter.exclude_values)
            entry['all_values'] = entry['all_values'] or dimension_filter.all_values


def _fill_authorizable_dimension_needs(filter_map, dimensions_type=SIMPLE):
    '''Fills filter map for authorizable dimensions that aren't explicity defined
    in the dimension to filters map based on AUTHORIZABLE_DIMENSIONS.
    '''
    authorizable_dimensions = set(
        current_app.zen_config.filters.AUTHORIZABLE_DIMENSIONS
    )
    hierarchical_dimensions = set(
        current_app.zen_config.datatypes.HIERARCHICAL_DIMENSIONS
    )
    auth_dimension_map = {
        SIMPLE: authorizable_dimensions - hierarchical_dimensions,
        HIERARCHICAL: authorizable_dimensions & hierarchical_dimensions,
    }
    for auth_dimension in auth_dimension_map[dimensions_type]:
        if auth_dimension not in filter_map:
            # Set default val
            # pylint: disable=W0104
            filter_map[auth_dimension]


def _categorize_query_needs(query_needs, dimensions_type=SIMPLE):
    '''Takes a list of QueryNeeds and categorizes them into dimension, and then
    into values that should be included, excluded, and allValues. Additionally,
    fills in values for authorizable dimensions that are not explicitly defined
    for a given user.
    '''
    dimension_to_values_map = get_empty_filter_map()
    for query_need in query_needs:
        populate_filter_map_with_need(dimension_to_values_map, query_need)
    _fill_authorizable_dimension_needs(
        dimension_to_values_map, dimensions_type=dimensions_type
    )
    return dimension_to_values_map


def _construct_single_filter(dimension_to_filters_map):
    '''Takes in a dict mapping dimension to permitted values and produces a
    single AND filter across each set. Simulates an OR filter across all
    dimension permutations.
    '''
    full_filter = EmptyFilter()
    for dimension_name, values in dimension_to_filters_map.items():
        if values['all_values']:
            continue

        is_filter_added = False
        if values['include']:
            full_filter &= Filter(
                type='in', dimension=dimension_name, values=list(values['include'])
            )
            is_filter_added = True
        if values['exclude']:
            full_filter &= ~Filter(
                type='in', dimension=dimension_name, values=list(values['exclude'])
            )
            is_filter_added = True

        # Need to do an additional check for no items
        if not is_filter_added:
            full_filter &= Dimension(dimension_name) == NO_FILTER_VAL

    return full_filter


def _sorted_values(values):
    return sorted(values, key=lambda value: (value is None, str(value)))


def _construct_hierarchical_filter(dimension_to_filters_map):
    '''Takes in a dict mapping dimension to permitted values and produces one
    filter for the whole hierarchy: included values are ORed across its
    dimensions, and excluded values, on whichever dimension, are ANDed onto that
    union. A dimension with neither contributes `NO_FILTER_VAL` to the union.

    Dimensions and values are visited in sorted order, so the same policies give
    the same filter in every process: the map's order follows set order, which
    changes with PYTHONHASHSEED.
    '''
    if any(values['all_values'] for values in dimension_to_filters_map.values()):
        return EmptyFilter()

    allowed_filter = EmptyFilter()
    excluded_filter = EmptyFilter()
    for dimension_name in sorted(dimension_to_filters_map):
        values = dimension_to_filters_map[dimension_name]
        if values['include']:
            allowed_filter |= Filter(
                type='in',
                dimension=dimension_name,
                values=_sorted_values(values['include']),
            )
        elif not values['exclude']:
            allowed_filter |= Dimension(dimension_name) == NO_FILTER_VAL
        if values['exclude']:
            excluded_filter &= ~Filter(
                type='in',
                dimension=dimension_name,
                values=_sorted_values(values['exclude']),
            )

    return allowed_filter & excluded_filter


def construct_query_need_from_policy(query_policy):
    '''Constructs a `QueryNeed` based on a `QueryPolicy` entity that is typically associated with
    a `User` or `Group` object.

    Parameters
    ----------
        query_policy: models.query_models.QueryPolicy
            The query policy held by a user or group that will serve as the template to construct
            a `QueryNeed` from.

    Returns
    ----------
    web.server.security.permissions.QueryNeed
        The constructed Query Need object that represents the query permissions held by
        `query_policy`.
    '''
    return QueryNeed(query_policy.dimension_filters)


class AuthorizedQueryClient:
    '''The query client for user requests.

    run_query ANDs the caller's policy into the query builder's query_filter and,
    for groupBy builders, its dimension_filter, which query-modifying aggregations
    rebuild from. A query whose Druid filter comes from anywhere else (a raw dict,
    a nested dataSource built outside the builder) is not covered, so the client
    has no run_raw_query: code that sends raw queries holds the system client and
    must take no user input.
    '''

    def __init__(self, query_client):
        self._query_client = query_client

    @apply_authorization_filters()
    def run_query(self, query):
        return self._query_client.run_query(query)
