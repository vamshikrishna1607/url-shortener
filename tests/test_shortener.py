"""
Tests the short-code generation logic (app/shortener.py), including the
concurrency property the whole design is built around: no two concurrent
requests can ever receive the same short code.
"""
from __future__ import annotations

import asyncio

import pytest

from app.shortener import (
    _encode_base62,
    create_short_code,
    get_click_count,
    record_click,
    resolve_short_code,
)


def test_encode_base62_is_deterministic_and_reversible_by_inspection():
    assert _encode_base62(0) == "0"
    assert _encode_base62(1) == "1"
    assert _encode_base62(61) == "Z"
    assert _encode_base62(62) == "10"  # rolls over, like any positional base


@pytest.mark.asyncio
async def test_create_and_resolve_round_trip():
    code = await create_short_code("https://example.com/hello")
    resolved = await resolve_short_code(code)
    assert resolved == "https://example.com/hello"


@pytest.mark.asyncio
async def test_resolve_unknown_code_returns_none():
    assert await resolve_short_code("doesnotexist") is None


@pytest.mark.asyncio
async def test_click_tracking():
    code = await create_short_code("https://example.com/x")
    assert await get_click_count(code) == 0
    await record_click(code)
    await record_click(code)
    assert await get_click_count(code) == 2


@pytest.mark.asyncio
async def test_concurrent_short_code_creation_never_collides():
    """The actual point of using an atomic Redis counter instead of
    random-code-and-retry: fire many creations at the exact same time and
    prove every single code that comes back is unique."""
    n = 200
    urls = [f"https://example.com/item/{i}" for i in range(n)]
    codes = await asyncio.gather(*(create_short_code(u) for u in urls))

    assert len(codes) == n
    assert len(set(codes)) == n, "collision: two concurrent requests got the same short code"
