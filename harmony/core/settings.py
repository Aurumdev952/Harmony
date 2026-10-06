'''Process settings, read once from the environment (BE-2).

`load_settings` refuses to return settings with a default secret (SEC-3) or a
missing `DRUID_HOST`, so a misconfigured web server, worker or pipeline run stops
at startup rather than hours in. Only the environment is read: no `.env` file and
no secrets directory.

Every image runs CPython 3.13 since WP-3b. The `typing` generics and
`typing_extensions.Annotated` date from the CPython 3.8 and PyPy 3.8 runtimes
before it.
'''

import functools
from typing import Optional

from pydantic import AfterValidator, SecretStr, ValidationError, ValidationInfo
from pydantic_core import ErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated


def refuse_default_secret(name: str, value: str) -> str:
    '''Return `value`, refusing an unset, blank or default secret (SEC-3).'''
    if value.strip().lower() in ('', 'changeme'):
        raise ValueError(
            f'{name} is unset, empty or the default "changeme"; refusing to start. '
            f'Set {name} to a random value, e.g. the output of `openssl rand -hex 32` '
            'or `python3 -c "import secrets; print(secrets.token_hex(32))"`.'
        )
    return value


def _refuse_default_secret(value: SecretStr, info: ValidationInfo) -> SecretStr:
    refuse_default_secret(info.field_name or '', value.get_secret_value())
    return value


Secret = Annotated[SecretStr, AfterValidator(_refuse_default_secret)]


class Settings(BaseSettings):
    '''Field names are the environment variable names.'''

    model_config = SettingsConfigDict(
        case_sensitive=True, frozen=True, validate_default=True, extra='ignore'
    )

    # Unset reads as empty, so it fails with the default-secret message.
    DEFAULT_SECRET_KEY: Secret = SecretStr('')
    # Required but may be empty, as config.settings allowed: compose passes
    # DRUID_HOST=${DRUID_HOST}, which is '' when the host variable is unset.
    DRUID_HOST: str

    NOREPLY_EMAIL: Optional[str] = None
    SUPPORT_EMAIL: Optional[str] = None
    # Redis is optional.
    REDIS_HOST: str = ''
    # Needed by the web server, not the pipeline.
    HASURA_HOST: Optional[str] = None
    OBJECT_STORAGE_ALIAS: Optional[str] = None
    # Needed by the web server, not the pipeline.
    MAPBOX_ACCESS_TOKEN: Optional[str] = None


def _describe(error: ErrorDetails) -> str:
    # Never include error['input']: it holds the raw value, which may be a secret.
    name = '.'.join(str(part) for part in error['loc'])
    if error['type'] == 'value_error':
        return str(error['ctx']['error'])
    if error['type'] == 'missing':
        return f'{name} is not set; refusing to start.'
    return f'{name}: {error["msg"]}; refusing to start.'


def load_settings() -> Settings:
    '''Read and validate settings from the environment, or raise RuntimeError
    naming every problem.'''
    try:
        return Settings()
    except ValidationError as error:
        problems = '\n'.join(_describe(detail) for detail in error.errors())
    raise RuntimeError(problems)


@functools.lru_cache(maxsize=None)
def get_settings() -> Settings:
    '''The process's settings, loaded on first call.'''
    return load_settings()
