"""Seeds the cached thumbnail the storage.retrieve.cached case reads.

The key is ``thumbnail:v2:<dashboard resource id>:<policy digest>``
(``web/server/redis/thumbnail_storage_service.py``, WP-0i). The dashboard only
exists once ``dashboard.create`` has run, so the case's ``seed`` step calls
``stack.sh seed thumbnail <resource id>`` just before the request. The replay
logs in as a site admin, whose digest is that of ``"superuser"``. A miss renders
through Urlbox, which the stack cannot reach, and answers ``""``; the case pins
the seeded value, so a key that drifts from the app's fails the replay.

Runs inside the web container, through flask-caching's own backend so the key
prefix and serialisation match what the app reads.
"""

import base64
import hashlib
import json
import os
import sys

from flask_caching.backends.rediscache import RedisCache
from redis.exceptions import AuthenticationError, ResponseError

# A 1x1 transparent PNG.
PIXEL = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()

SUPERUSER_DIGEST = hashlib.sha256(
    json.dumps("superuser", sort_keys=True).encode()
).hexdigest()


def cache(password):
    return RedisCache(
        host=os.environ["REDIS_HOST"],
        password=password,
        key_prefix=f"zen-{os.environ['ZEN_ENV']}-",
    )


def main() -> None:
    key = f"thumbnail:v2:{int(sys.argv[1])}:{SUPERUSER_DIGEST}"
    try:
        cache(None).set(key, PIXEL, timeout=0)
    except (AuthenticationError, ResponseError):
        cache(os.environ["REDIS_PASSWORD"]).set(key, PIXEL, timeout=0)
    print(f"contract stack: seeded the thumbnail of resource {sys.argv[1]}")


if __name__ == "__main__":
    main()
