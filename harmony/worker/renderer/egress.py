'''Which URLs the rendered page may load (SEC-10).'''

from typing import Optional
from urllib.parse import urlsplit

DEFAULT_PORTS = {'http': 80, 'https': 443}


def origin_of(url: str) -> Optional[tuple[str, str, int]]:
    '''The (scheme, host, port) of an http(s) URL with no credentials, else None.'''
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return parts.scheme, parts.hostname, port or DEFAULT_PORTS[parts.scheme]


def parse_origins(value: str) -> tuple[str, ...]:
    '''A comma-separated list of bare `scheme://host[:port]` origins, normalised
    with the port spelt out. Raises ValueError for anything else.
    '''
    origins = []
    for item in filter(None, (part.strip() for part in value.split(','))):
        origin = origin_of(item)
        parts = urlsplit(item)
        if origin is None or parts.path not in ('', '/') or parts.query:
            raise ValueError(f'not a bare http(s) origin: {item!r}')
        scheme, host, port = origin
        bracketed = f'[{host}]' if ':' in host else host
        origins.append(f'{scheme}://{bracketed}:{port}')
    return tuple(origins)


def is_allowed(
    url: str,
    allowed_origin: str,
    map_origins: tuple[str, ...] = (),
    *,
    is_navigation: bool = False,
) -> bool:
    '''Whether the page may request `url`: its own origin, inline `data:` and
    `about:blank`, and `blob:` URLs created by its own origin. Map origins may be
    fetched but never navigated to.
    '''
    if url == 'about:blank' or url.startswith('data:'):
        return True
    if url.startswith('blob:'):
        url = url[len('blob:') :]
    origin = origin_of(url)
    if origin is None:
        return False
    if origin == origin_of(allowed_origin):
        return True
    return not is_navigation and origin in {origin_of(m) for m in map_origins}
