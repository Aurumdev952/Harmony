import base64
import hashlib
import json
import time

from cachelib import FileSystemCache
from flask import current_app
from flask_user import current_user

from web.server.routes.views.page_renderer import grid_dashboard_to_thumbnail
from web.server.routes.views.query_policy import canonical_policy
from web.server.security.permissions import SuperUserPermission
from web.server.security.signal_handlers import render_token_query_needs

EXPIRATION_SEC = 1209600  # Update thumbnail image every 2 weeks.
PENDING = 'PENDING'
PENDING_STATE_TIMEOUT = 600


def query_policy_fingerprint():
    '''A stable digest of the query policy a render made as the current user runs
    under. Two users share a cached thumbnail only when it is the same.
    '''
    if SuperUserPermission().can():
        policy = 'superuser'
    else:
        policy = canonical_policy(render_token_query_needs())
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def get_thumbnail_storage_name(dashboard):
    return f'thumbnail:v2:{dashboard.resource_id}:{query_policy_fingerprint()}'


def render_thumbnail(dashboard):
    response = grid_dashboard_to_thumbnail(
        name=dashboard.slug, auth_user_email=current_user.username
    )
    if not response or response.status_code != 200:
        return ''
    return base64.b64encode(response.content).decode()


def _keeps_expired_entries(cache):
    '''FileSystemCache leaves an expired entry on disk, so `get` misses it while
    `add` still fails until it is deleted. Redis drops it: there, a miss after a
    failed `add` means the holder has just released its claim, and another
    caller may already hold a new one that must not be deleted.
    '''
    return isinstance(getattr(cache, 'cache', cache), FileSystemCache)


def retrieve_item(dashboard):
    '''Returns the current user's thumbnail of the dashboard, rendering it as
    them when no user with the same query policy has one cached.
    '''
    cache = current_app.cache
    storage_key = get_thumbnail_storage_name(dashboard)
    deadline = time.monotonic() + PENDING_STATE_TIMEOUT
    while not cache.add(storage_key, PENDING, timeout=PENDING_STATE_TIMEOUT):
        value = cache.get(storage_key)
        if value and value != PENDING:
            return value
        if time.monotonic() >= deadline:
            return ''
        if value is None and _keeps_expired_entries(cache):
            cache.delete(storage_key)
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
