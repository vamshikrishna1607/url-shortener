"""
Tests the sliding-window rate limiter (app/rate_limiter.py), including the
race condition the Lua script exists to prevent: under truly concurrent
requests, the limiter must never let more than the configured limit
through, even though multiple requests are checking "am I under the
limit?" at the exact same instant.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.rate_limiter import is_allowed


@pytest.mark.asyncio
async def test_allows_requests_under_the_limit():
    client = "client-a"
    for _ in range(settings.rate_limit_requests):
        assert await is_allowed(client) is True


@pytest.mark.asyncio
async def test_blocks_requests_over_the_limit():
    client = "client-b"
    for _ in range(settings.rate_limit_requests):
        assert await is_allowed(client) is True
    # One more than the limit must be rejected.
    assert await is_allowed(client) is False


@pytest.mark.asyncio
async def test_different_clients_have_independent_limits():
    client_a, client_b = "client-c", "client-d"
    for _ in range(settings.rate_limit_requests):
        assert await is_allowed(client_a) is True
    # client_b has made zero requests, so it should still be fully allowed
    # even though client_a just maxed out.
    assert await is_allowed(client_b) is True


@pytest.mark.asyncio
async def test_window_expiry_allows_requests_again_after_waiting():
    client = "client-e"
    for _ in range(settings.rate_limit_requests):
        assert await is_allowed(client) is True
    assert await is_allowed(client) is False

    # Wait for the (short, test-configured) window to fully pass.
    await asyncio.sleep(settings.rate_limit_window_seconds + 0.5)
    assert await is_allowed(client) is True


@pytest.mark.asyncio
async def test_concurrent_requests_never_exceed_the_limit():
    """The real test of the Lua script's atomicity: fire 3x the limit's
    worth of requests for one client, ALL AT ONCE via asyncio.gather, and
    prove that exactly `limit` of them were allowed - not more. Without
    the Lua script being atomic, concurrent requests could all read the
    same "count so far" before any of them writes, letting more than the
    limit through."""
    client = "client-concurrent"
    n = settings.rate_limit_requests * 3
    results = await asyncio.gather(*(is_allowed(client) for _ in range(n)))

    allowed_count = sum(1 for r in results if r)
    assert allowed_count == settings.rate_limit_requests, (
        f"expected exactly {settings.rate_limit_requests} requests allowed under "
        f"concurrency, got {allowed_count} (race condition in the limiter)"
    )
