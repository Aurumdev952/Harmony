from datetime import timedelta
from urllib.parse import urlparse, urlsplit

import requests
from flask import current_app, request
from requests import RequestException
from flask_jwt_extended import create_access_token
from werkzeug.exceptions import HTTPException

from config import settings
from log import LOG
from models.alchemy.dashboard import Dashboard
from web.server.data.data_access import Transaction
from web.server.security.signal_handlers import RENDER_TOKEN_QUERY_NEEDS

# Make the URLBOX API URL configurable in case a reverse proxy is necessary.
URLBOX_API_URL = settings.getenv("URLBOX_API_URL", "https://api.urlbox.io")

# Override the JWT token expiration time set in Flask config
# to enable the dashboard pdf renderer to authenticate
JWT_TOKEN_EXPIRATION_TIME = 120

# Request params a caller may pass through to urlbox. `url` and `cookie` would
# send the minted token to another page, and `force` would let urlbox answer
# from its own cache, so they are deliberately absent.
SUPPORTED_RENDERING_PARAMS = [
    "delay",
    "fail_on_4xx",
    "fail_on_5xx",
    "fail_if_selector_present",
    "max_height",
    "wait_to_leave",
    "max_section_height",
    "wait_timeout",
    "detect_full_height",
    "allow_infinite",
    "width",
    "media",
    "height",
    "pdf_page_size",
    "pdf_fit_to_page",
    "skip_scroll",
    "scroll_increment",
    "scroll_delay",
    "pdf_orientation",
    "full_page",
]


def dashboard_page_args(dashboard_url):
    """The locale and session hash in a link to a dashboard page.

    Nothing else is taken from a caller's link: a render always loads this app's
    own dashboard page, because it carries a token for the user it renders as.
    """
    if not dashboard_url:
        return None, ""
    parsed = urlparse(dashboard_url)
    try:
        endpoint, args = current_app.url_map.bind("").match(parsed.path)
    except HTTPException:
        endpoint, args = None, {}
    locale = args.get("locale") if endpoint == "dashboard.grid_dashboard" else None
    session_hash = parsed.fragment[2:] if parsed.fragment.startswith("h=") else ""
    return locale, session_hash


def deployment_origin(deployment_base_url):
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


def deployment_dashboard_url(name, locale=None):
    """The dashboard page's absolute URL on the deployment's configured origin.

    Never built from the request: renders send a token to this URL, and emails
    send it to their recipients. `url_for` would prefix the request's script
    root, which gunicorn takes from a `SCRIPT_NAME` request header.
    """
    origin = deployment_origin(current_app.zen_config.general.DEPLOYMENT_BASE_URL)
    path = current_app.url_map.bind("").build(
        "dashboard.grid_dashboard", {"locale": locale, "name": name}
    )
    return origin + path


def get_dashboard_downloadable_url(locale, name, output_format, session_hash):
    dashboard_url = deployment_dashboard_url(name, locale)
    hash_suffix = f"#h={session_hash}" if session_hash else ""
    dash_url = (
        f"{dashboard_url}?screenshot=1&pdf=1{hash_suffix}"
        if output_format == "pdf"
        else f"{dashboard_url}?screenshot=1{hash_suffix}"
    )
    return dash_url


def grid_dashboard_urlbox_renderer(
    output_format,
    name,
    auth_user_email,
    locale=None,
    is_thumbnail=False,
    session_hash="",
    request_args=None,
):
    """Send a request to the urlbox.io to generate a PDF or image, signed in as
    `auth_user_email`. `request_args` defaults to the current request's args.
    """
    dash_url = get_dashboard_downloadable_url(locale, name, output_format, session_hash)
    if is_thumbnail:
        dash_url += "&thumbnail=1"
    api_key = settings.URLBOX_API_KEY
    req_url = f"{URLBOX_API_URL}/v1/{api_key}/{output_format}"
    with Transaction() as transaction:
        resource_id = (
            transaction.find_all_by_fields(Dashboard, {"slug": name}).one().resource_id
        )
    token = create_access_token(
        identity=auth_user_email,
        expires_delta=timedelta(seconds=JWT_TOKEN_EXPIRATION_TIME),
        user_claims={
            "needs": [
                ["view_resource", resource_id, "dashboard"],
            ],
            "query_needs": RENDER_TOKEN_QUERY_NEEDS,
        },
    )

    params = {
        "allow_infinite": "true",
        "cookie": f"accessKey={token}",
        "fail_if_selector_missing": "true",
        "fail_on_5xx": "true",
        "force": "true",
        "ttl": 86400,
        "url": dash_url,
        "wait_for": "#dashboard-load-success",
        "wait_timeout": 120000,
        "timeout": 60000,
    }

    if output_format == "pdf":
        params.update(
            {
                "media": "screen",
                "pdf_page_size": "A4",
                'js': (
                    "window.addEventListener('resize',() => "
                    "{let svgs = document.querySelectorAll('.visualization > "
                    "div > svg');svgs.forEach((svg) => {svg.setAttribute('height', "
                    "'1px');});});"
                ),
                "css": "svg:not(:root) { overflow: visible !important;}",
                "delay": 10000,
            }
        )
    elif output_format == "jpg":
        params.update({"quality": 100, "full_page": True, "width": 1280})

    # add dynamically added params and might override set params
    overrides = request.args if request_args is None else request_args
    for _param in SUPPORTED_RENDERING_PARAMS:
        param_value = overrides.get(_param)
        if param_value:
            params[_param] = param_value

    # The request URL carries the API key and the minted token, and requests puts
    # it in its exception messages, so neither the URL nor the exception is logged.
    dashboard_path = urlparse(dash_url).path
    try:
        res = requests.get(req_url, params=params, stream=True, timeout=300)
    except RequestException as error:
        LOG.error(
            "Urlbox request for %s of %s failed: %s",
            output_format,
            dashboard_path,
            type(error).__name__,
        )
        return None
    if res.status_code != 200:
        LOG.error(
            "Urlbox failed to generate %s for %s with status code %s",
            output_format,
            dashboard_path,
            res.status_code,
        )
    return res


def grid_dashboard_to_pdf(locale=None, name=None, *, auth_user_email, session_hash=""):
    return grid_dashboard_urlbox_renderer(
        "pdf", name, auth_user_email, locale=locale, session_hash=session_hash
    )


def grid_dashboard_to_thumbnail(locale=None, name=None, *, auth_user_email):
    # A thumbnail is cached and shared, so no caller-supplied param may shape it.
    return grid_dashboard_urlbox_renderer(
        "png", name, auth_user_email, locale=locale, is_thumbnail=True, request_args={}
    )


def grid_dashboard_to_image(
    locale=None, name=None, *, auth_user_email, session_hash=""
):
    return grid_dashboard_urlbox_renderer(
        "jpg", name, auth_user_email, locale=locale, session_hash=session_hash
    )
