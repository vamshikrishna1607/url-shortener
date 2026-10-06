"""
A sliding-window rate limiter backed by Redis.

Plain-English version of the algorithm: for each client, keep a running
list of the exact timestamps of their recent requests. To check a new
request, throw away any timestamps older than the window (e.g. older than
60 seconds ago), count what's left, and allow the request only if that
count is still under the limit.

Redis data structure used: a "sorted set" (ZSET) per client, where each
member is one request and its score is the timestamp it happened at.
Sorted sets are the right fit here because Redis can remove everything
below a score (ZREMRANGEBYSCORE) and count what's left (ZCARD) in one
command each, in O(log n) time - there's no need to pull every timestamp
into Python and filter it there.

Why this has to run as a Lua script instead of plain Python+Redis calls:
Redis runs every command on a single thread, which makes *each individual
command* atomic - but three separate commands (remove old, count, add
new) are NOT atomic together. Picture two requests arriving in the same
instant, both under the limit of 5: both read "4 requests so far," both
decide "allowed," both add themselves - and now the client has made 6
requests even though the limit was 5. A Lua script is itself just one
Redis command as far as atomicity is concerned (Redis runs the whole
script without interruption), which is what closes that race.
tests/test_rate_limiter.py proves this by firing many concurrent requests
at once and asserting the limiter never allows more than the configured
maximum through.
"""
from __future__ import annotations

import time
import uuid

from .config import settings
from .redis_client import redis_client

_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local window_seconds = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local current = redis.call('ZCARD', key)

if current < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window_seconds)
    return 1
else
    return 0
end
"""

_script_sha: str | None = None


async def _get_script_sha() -> str:
    global _script_sha
    if _script_sha is None:
        _script_sha = await redis_client.script_load(_SLIDING_WINDOW_SCRIPT)
    return _script_sha


async def is_allowed(client_id: str) -> bool:
    """Returns True if this client is still under the rate limit and the
    request should proceed (and records it), False if they've hit the
    limit and should be rejected with 429 Too Many Requests."""
    now = time.time()
    window_start = now - settings.rate_limit_window_seconds
    # A unique member per call - two requests in the same millisecond must
    # still count as two separate entries in the sorted set.
    member = f"{now}:{uuid.uuid4().hex}"

    sha = await _get_script_sha()
    try:
        result = await redis_client.evalsha(
            sha,
            1,
            f"urlshort:ratelimit:{client_id}",
            now,
            window_start,
            settings.rate_limit_requests,
            member,
            settings.rate_limit_window_seconds,
        )
    except Exception:
        # NOSCRIPT can happen if Redis's script cache was flushed; reload
        # and retry once rather than failing every request after a flush.
        global _script_sha
        _script_sha = None
        sha = await _get_script_sha()
        result = await redis_client.evalsha(
            sha,
            1,
            f"urlshort:ratelimit:{client_id}",
            now,
            window_start,
            settings.rate_limit_requests,
            member,
            settings.rate_limit_window_seconds,
        )
    return bool(result)
