import base64
import time

from flask import current_app
from flask_user import current_user

from web.server.routes.views.page_renderer import (
    RendersInFlight,
    claim,
    grid_dashboard_to_thumbnail,
)
from web.server.security.signal_handlers import query_policy_fingerprint

EXPIRATION_SEC = 1209600  # Update thumbnail image every 2 weeks.
PENDING = 'PENDING'
PENDING_STATE_TIMEOUT = 600
# The Overview page asks for every dashboard's thumbnail at once, and an account
# renders one at a time, so an uncached thumbnail waits this long for the
# account's render slot before it is left empty for the next visit.
THUMBNAIL_SLOT_WAIT_SECONDS = 10


def get_thumbnail_storage_name(dashboard):
    return f'thumbnail:v2:{dashboard.resource_id}:{query_policy_fingerprint()}'


def render_thumbnail(dashboard):
    try:
        rendered = grid_dashboard_to_thumbnail(
            name=dashboard.slug,
            auth_user_email=current_user.username,
            slot_wait_seconds=THUMBNAIL_SLOT_WAIT_SECONDS,
        )
    except RendersInFlight:
        # Not cached, so the next view renders it.
        return ''
    if rendered is None:
        return ''
    return base64.b64encode(rendered.content).decode()


def retrieve_item(dashboard):
    '''Returns the current user's thumbnail of the dashboard, rendering it as
    them when no user with the same query policy has one cached.
    '''
    cache = current_app.cache
    storage_key = get_thumbnail_storage_name(dashboard)
    deadline = time.monotonic() + PENDING_STATE_TIMEOUT
    while not claim(cache, storage_key, PENDING, PENDING_STATE_TIMEOUT):
        value = cache.get(storage_key)
        if value and value != PENDING:
            return value
        if time.monotonic() >= deadline:
            return ''
        time.sleep(1)

    new_base64_img = ''
    try:
        new_base64_img = render_thumbnail(dashboard)
    finally:
        if new_base64_img:
            cache.set(storage_key, new_base64_img, timeout=EXPIRATION_SEC)
        else:
            cache.delete(storage_key)
    return new_base64_img
