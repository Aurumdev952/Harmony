'''LAST_VALUE: an aggregator that only sees the rows at the latest timestamp.

Calculations wrap an inner aggregator in the shape of the Zenysis `aggregateLast`
extension, `{'type': 'aggregateLast', 'aggregator': inner}`. Within each result
row the extension keeps the largest `__time` among the rows that reach it and
applies `inner` to every row with that timestamp, so ties all count. Partial
results from different segments merge the same way: the later timestamp wins,
and equal timestamps are combined with `inner`.

The extension exists for Druid 0.23 only and fails under SQL-compatible nulls
(WP-8a, N3). `build_last_value` serialises the wrapper either as the extension
or as Druid's built-in `expression` aggregator, which keeps a
`[timestamp, value]` accumulator with the same semantics.
`settings.DRUID_LAST_VALUE` (`HARMONY_DRUID_LAST_VALUE`, checked when settings
load) picks one: `extension` (default) or `native`. WP-8b switches every
deployment to `native` and deletes the extension (decision 0007, rule 5).
'''

import json

from config import settings

EXTENSION = 'extension'

# How two values at the same timestamp combine, per inner aggregator type.
_COMBINE = {
    'doubleSum': '{} + {}',
    'doubleMax': 'greatest({}, {})',
    'doubleMin': 'least({}, {})',
}

# Earlier than any timestamp. Doubles hold every epoch millisecond exactly up
# to 2^53, so the accumulator can keep the timestamp next to a double value.
_BEFORE_ALL_TIME = '-9007199254740992.0'

# Bytes Druid reserves per group for the accumulator (default 1024). A nullable
# ARRAY<DOUBLE> of two takes 23: a null byte, a 4-byte length, and a null byte
# plus 8 bytes per element. A value that does not fit fails the query; it is
# never truncated.
MAX_SIZE_BYTES = 32


def build_last_value(name: str, aggregator: dict) -> dict:
    '''Serialise an `aggregateLast` wrapper as the Druid aggregator `name`.'''
    if settings.DRUID_LAST_VALUE == EXTENSION:
        return {**aggregator, 'name': name}
    return native_last_value(name, aggregator['aggregator'])


def native_last_value(name: str, inner: dict) -> dict:
    if inner['type'] not in _COMBINE:
        raise ValueError(f'LAST_VALUE cannot wrap a {inner["type"]} aggregator')
    combine = _COMBINE[inner['type']]
    # `fold` binds the accumulator next to the fields, and `combine` next to the
    # aggregator's own name. A field or name equal to the accumulator would
    # shadow it, and Druid would silently drop partial results.
    accumulator = '__acc'
    while accumulator in (name, '__time', inner['fieldName']):
        accumulator = f'_{accumulator}'

    def latest(time: str, value: str) -> str:
        '''`[time, value]` if it is later than the accumulator, the two
        combined at the same time, else the accumulator. Arrays are only ever
        read through `array_offset`: Druid 0.23 rejects an expression that also
        uses an array variable as a bare value.'''
        acc_time = f'array_offset({accumulator}, 0)'
        acc_value = f'array_offset({accumulator}, 1)'
        return (
            f'if({time} > {acc_time}, array({time}, {value}), '
            f'if({time} == {acc_time}, '
            f'array({acc_time}, {combine.format(acc_value, value)}), '
            f'array({acc_time}, {acc_value})))'
        )

    # A row's metric is null only under SQL-compatible nulls; legacy Druid and
    # the extension read it as 0.
    row_value = f'nvl({_identifier(inner["fieldName"])}, 0.0)'
    # `combine` merges a partial result, bound to the aggregator's own name,
    # into the accumulator.
    partial = _identifier(name)
    return {
        'type': 'expression',
        'name': name,
        'fields': ['__time', inner['fieldName']],
        'accumulatorIdentifier': accumulator,
        'initialValue': f'array({_BEFORE_ALL_TIME}, 0.0)',
        'fold': latest('cast("__time", \'DOUBLE\')', row_value),
        'combine': latest(f'array_offset({partial}, 0)', f'array_offset({partial}, 1)'),
        # With no rows the result is the initial 0, as on legacy Druid, rather
        # than null; strict-null fields (`__count`) still turn it into null.
        'isNullUnlessAggregated': False,
        'shouldCombineAggregateNullInputs': False,
        'finalize': 'array_offset(o, 1)',
        'maxSizeBytes': MAX_SIZE_BYTES,
    }


def _identifier(column: str) -> str:
    '''A Druid expression identifier. JSON string escapes are Druid's too.'''
    return json.dumps(column)
