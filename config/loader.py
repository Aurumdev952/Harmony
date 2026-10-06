import os

from harmony.core.deployment import load_deployment


def import_configuration_module(zenysis_environment=None):
    return load_deployment(zenysis_environment or os.getenv('ZEN_ENV') or '')
