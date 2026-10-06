import related

from pydruid.utils.filters import Filter

from data.query.models.query_filter.query_filter import (
    QueryFilter,
    druid_dimension_value,
)


@QueryFilter.register_subtype
@related.immutable
class InFilter(QueryFilter):
    '''The InFilter represents a filtering of values IN the specified dimension.'''

    # Dimension id
    dimension = related.StringField()
    values = related.SequenceField(str)
    type = related.StringField('IN')

    def to_druid(self):
        values = [druid_dimension_value(value) for value in self.values]
        return Filter(type='in', dimension=self.dimension, values=values)
