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


def is_allowed(url: str, allowed_origin: str) -> bool:
    '''Whether the page may request `url`: its own origin, inline `data:` and
    `about:blank`, and `blob:` URLs created by its own origin.
    '''
    if url == 'about:blank' or url.startswith('data:'):
        return True
    if url.startswith('blob:'):
        url = url[len('blob:') :]
    origin = origin_of(url)
    return origin is not None and origin == origin_of(allowed_origin)
