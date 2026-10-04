from config.harmony_demo.general import DEPLOYMENT_NAME
from db.druid.metadata import DruidMetadata

############################################################################
# Database settings


def __getattr__(name):
    # DATASOURCE, the latest Druid datasource to use, is looked up on first
    # access so that importing deployment config never calls Druid.
    if name != 'DATASOURCE':
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    datasource = DruidMetadata.get_most_recent_datasource(DEPLOYMENT_NAME)
    globals()['DATASOURCE'] = datasource
    return datasource
