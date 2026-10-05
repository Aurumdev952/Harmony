from typing import TYPE_CHECKING

from config.template.general import DEPLOYMENT_NAME
from db.druid.metadata import DruidMetadata

if TYPE_CHECKING:
    from db.druid.datasource import SiteDruidDatasource

############################################################################
# Database settings


def __getattr__(name: str) -> 'SiteDruidDatasource':
    # DATASOURCE, the latest Druid datasource to use, is looked up on first
    # access so that importing deployment config never calls Druid.
    if name != 'DATASOURCE':
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    datasource = DruidMetadata.get_most_recent_datasource(DEPLOYMENT_NAME)
    globals()['DATASOURCE'] = datasource
    return datasource
