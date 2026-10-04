"""Seeds the Redis thumbnail the storage/retrieve case reads.

A thumbnail miss renders through Urlbox, which the stack cannot reach, and
leaves a PENDING marker that makes later reads wait 10 minutes. Runs inside the
web container, through flask-caching's own backend so the key prefix and
serialisation match what the app reads.
"""

import base64
import os

from flask_caching.backends.rediscache import RedisCache
from redis.exceptions import AuthenticationError, ResponseError

# A 1x1 transparent PNG; only its type matters to the contract.
PIXEL = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()


def cache(password):
    return RedisCache(
        host=os.environ["REDIS_HOST"],
        password=password,
        key_prefix=f"zen-{os.environ['ZEN_ENV']}-",
    )


def main() -> None:
    try:
        store = cache(None)
        store.set("thumbnail_contract-dashboard", PIXEL, timeout=0)
    except (AuthenticationError, ResponseError):
        store = cache(os.environ["REDIS_PASSWORD"])
        store.set("thumbnail_contract-dashboard", PIXEL, timeout=0)
    print("contract stack: seeded thumbnail_contract-dashboard")


if __name__ == "__main__":
    main()
