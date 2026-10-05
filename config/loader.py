import os

from harmony.core.deployment import load_deployment


def get_configuration_module():
    try:
        from flask import current_app

        if current_app:
            return current_app.zen_config
    except ImportError:
        pass

    return import_configuration_module()


def import_configuration_module(zenysis_environment=None):
    return load_deployment(zenysis_environment or os.getenv('ZEN_ENV') or '')
