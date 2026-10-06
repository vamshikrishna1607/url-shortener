"""
A single shared connection to Redis, reused across the whole app.

Redis, in one sentence: an in-memory key-value store - think of it as a
dictionary that lives in RAM, is shared across every process/server that
connects to it, and is fast enough to answer in well under a millisecond.
That's what makes it the right tool for the two things this app needs to
do on every single request: redirect a short code instantly, and check a
rate limit instantly.

We use redis.asyncio (the async client) because FastAPI is an async
framework - using the sync redis client here would block the whole event
loop on every Redis call, defeating the point of using an async framework
at all.
"""
from __future__ import annotations

import redis.asyncio as redis

from .config import settings

# decode_responses=True means Redis replies come back as Python str
# instead of bytes - slightly slower, much easier to work with and read.
#
# max_connections caps the connection pool: redis-py defaults to 100,
# which a traffic spike (or this project's own concurrency tests, which
# deliberately fire 200 requests at once to prove the rate limiter and
# short-code generator are race-free) can exceed, raising
# MaxConnectionsError instead of just queueing. Raised explicitly here
# rather than left at the default - sizing the pool for expected
# concurrency is a real production decision, not just a test workaround.
redis_client: redis.Redis = redis.from_url(
    settings.redis_url, decode_responses=True, max_connections=300
)


async def ping() -> bool:
    """Used by /health to prove the app can actually reach Redis, not just
    that the process is running."""
    return await redis_client.ping()
