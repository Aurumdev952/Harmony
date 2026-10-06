from typing import Optional

import related

from util.related.polymorphic_model import build_polymorphic_base


def druid_dimension_value(value: str) -> Optional[str]:
    '''The value to post for a stored or submitted dimension value.

    Stored filters write "no value" as '' (a municipality whose state is unknown
    is `MunicipalityName = X AND StateName = ''`). Legacy Druid stores '' as null,
    so '' matched the rows with no value. Under SQL-compatible nulls, the only mode
    from Druid 28 on, it matches no row, so post null to keep that meaning.
    '''
    return None if value == '' else value


# TODO: fix type error
@related.immutable
class QueryFilter(build_polymorphic_base()):  # type: ignore[misc]
    '''The QueryFilter model stores a full filter object that can be applied to a query.'''

    def to_druid(self):
        raise ValueError('to_druid must be implemented by subclass.')

    def is_valid(self) -> bool:
        return True
