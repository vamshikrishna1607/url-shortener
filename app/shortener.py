"""
Short-code generation and lookup.

The core design decision this file makes: generate short codes from an
atomically-incrementing counter (Redis INCR), encoded as base62 - instead
of the more obvious-looking approach of "generate a random 6-character
code, check if it's taken, retry if so."

Why that matters: Redis executes every command on a single thread, so
INCR is *atomic* - if 1,000 "shorten this URL" requests hit the server in
the same millisecond, Redis still hands out 1,000 different numbers, one
each, with mathematical certainty. No two requests can ever receive the
same number. That means no collision is even possible, and there's no
retry loop needed. The random-code approach, by contrast, has to check
"is this code already used?" and retry on a clash - which gets slower and
more complex exactly as the number of stored URLs grows, which is the
opposite of what you want from something designed to scale.
tests/test_shortener.py proves this empirically: it fires many concurrent
requests and asserts every single code that comes back is unique.
"""
from __future__ import annotations

from .redis_client import redis_client

# Base62 = digits + lowercase + uppercase letters. Using all 62 characters
# (instead of just digits, i.e. base10) means each extra character in the
# short code covers 62x more codes rather than 10x - how real-world
# shorteners keep codes short (bit.ly-style, 6-7 characters) while still
# covering billions of URLs.
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(_ALPHABET)

COUNTER_KEY = "urlshort:counter"


def _encode_base62(n: int) -> str:
    if n == 0:
        return _ALPHABET[0]
    digits = []
    while n:
        n, rem = divmod(n, _BASE)
        digits.append(_ALPHABET[rem])
    return "".join(reversed(digits))


async def create_short_code(original_url: str) -> str:
    """Atomically claim the next integer ID from Redis, encode it as
    base62, and store the mapping. Safe to call concurrently - see the
    module docstring for why."""
    # INCR both creates the counter (starting at 0) on first use and
    # atomically increments it on every call - one round trip, no race.
    next_id = await redis_client.incr(COUNTER_KEY)
    code = _encode_base62(next_id)
    await redis_client.set(f"urlshort:code:{code}", original_url)
    return code


async def resolve_short_code(code: str) -> str | None:
    """Look up the original URL for a short code, or None if it doesn't
    exist. Also records a click - see record_click()."""
    return await redis_client.get(f"urlshort:code:{code}")


async def record_click(code: str) -> None:
    await redis_client.incr(f"urlshort:clicks:{code}")


async def get_click_count(code: str) -> int:
    count = await redis_client.get(f"urlshort:clicks:{code}")
    return int(count) if count is not None else 0
