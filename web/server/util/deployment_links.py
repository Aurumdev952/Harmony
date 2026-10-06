"""Absolute links to this deployment's pages, built from DEPLOYMENT_BASE_URL.

Never from the request: the caller chooses the Host header, and gunicorn copies
a `SCRIPT_NAME` request header into the WSGI environ, so `url_for(...,
_external=True)` can point a mailed reset link, or a render token, at another
host.
"""

import re
from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

from flask import current_app
from werkzeug.exceptions import HTTPException

from config.locales import LOCALES

# A session hash in a link's fragment. A page opened from a shared link already
# ends in `#h=<old>`, and the share dialog appends `#h=<new>`, so the last one
# counts. Anything else in the fragment is dropped rather than copied into a
# mailed or rendered URL.
_SESSION_HASH = re.compile(r"(?:^|#)h=([0-9A-Za-z_-]{1,128})(?=#|$)")


def deployment_origin(deployment_base_url: Optional[str]) -> str:
    """The configured DEPLOYMENT_BASE_URL as a bare https origin, or ValueError.

    Renders send a minted token to this origin and emails send links to it, so it
    must name exactly one host: no userinfo (`https://real@attacker`), path,
    query or fragment.
    """
    parts = urlsplit(deployment_base_url or "")
    try:
        has_valid_port = parts.port is None or parts.port > 0
    except ValueError:
        has_valid_port = False
    if (
        not has_valid_port
        or parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "DEPLOYMENT_BASE_URL must be an https origin with no userinfo, path, "
            f"query or fragment: {deployment_base_url!r}"
        )
    return f"https://{parts.netloc}"


def deployment_url(endpoint: str, **values: Any) -> str:
    """`endpoint`'s absolute URL on the configured origin. Values the rule does
    not take become the query string; `None` values are left out."""
    origin = deployment_origin(current_app.zen_config.general.DEPLOYMENT_BASE_URL)
    return origin + current_app.url_map.bind("").build(endpoint, values)


def page_args(link: Optional[str], endpoint: str) -> Tuple[Optional[str], str]:
    """The locale and session hash in a caller's link to `endpoint`'s page.

    Nothing else is taken from the link: its host, path and query are ignored,
    and a locale is kept only if it is one Harmony has.
    """
    try:
        parts = urlsplit(link or "")
    except ValueError:
        return None, ""
    try:
        matched, args = current_app.url_map.bind("").match(parts.path)
    except HTTPException:
        matched, args = None, {}
    locale = args.get("locale") if matched == endpoint else None
    session_hashes = _SESSION_HASH.findall(parts.fragment)
    return (
        locale if locale in LOCALES else None,
        session_hashes[-1] if session_hashes else "",
    )


def shared_page_url(link: Optional[str], endpoint: str, **values: Any) -> str:
    """The page a share email links to: `endpoint` on the configured origin, in
    the locale of the caller's `link` and with its session hash."""
    locale, session_hash = page_args(link, endpoint)
    url = deployment_url(endpoint, locale=locale, **values)
    return f"{url}#h={session_hash}" if session_hash else url
