"""
Test configuration. Sets environment variables BEFORE any `app.*` module is
imported anywhere in the test session, since app.config.settings is a
module-level singleton read once at import time - setting env vars later
(e.g. inside a fixture) would be too late.

Uses a real Redis instance (no mocking) - REDIS_URL / URLSHORT_REDIS_URL
must point at one. Locally that's redis-server on localhost; in CI
(.github/workflows/ci.yml) it's a real `redis:7` service container. Either
way, these tests exercise the actual Redis commands and the actual Lua
script, not a fake standing in for them - that matters specifically
because the thing being tested (atomicity under concurrency) can't be
verified against a mock.
"""
import os

os.environ.setdefault("URLSHORT_REDIS_URL", "redis://localhost:6379/0")
# Small, fast values so the sliding-window-expiry tests don't need to
# sleep for a full production-sized window (60s) to prove entries expire.
os.environ.setdefault("URLSHORT_RATE_LIMIT_REQUESTS", "10")
os.environ.setdefault("URLSHORT_RATE_LIMIT_WINDOW_SECONDS", "2")

import pytest
import pytest_asyncio

from app.redis_client import redis_client


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis():
    """Flush the test DB before every test so tests don't see each other's
    counters/rate-limit state. Safe because this points at a dedicated
    test Redis instance/DB, never a real one."""
    await redis_client.flushdb()
    yield
    await redis_client.flushdb()
