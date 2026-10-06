"""
End-to-end tests of the FastAPI endpoints themselves, using httpx's
ASGITransport to call the app in-process (no real TCP socket needed) while
still hitting the real Redis backend configured in conftest.py.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "redis": True}


@pytest.mark.asyncio
async def test_shorten_then_redirect_then_stats(client):
    async with client as c:
        resp = await c.post("/shorten", json={"url": "https://example.com/some/page"})
        assert resp.status_code == 201
        body = resp.json()
        code = body["short_code"]
        assert body["original_url"] == "https://example.com/some/page"
        assert body["short_url"].endswith(f"/{code}")

        redirect_resp = await c.get(f"/{code}", follow_redirects=False)
        assert redirect_resp.status_code == 307
        assert redirect_resp.headers["location"] == "https://example.com/some/page"

        stats_resp = await c.get(f"/stats/{code}")
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["clicks"] == 1  # the redirect above counted as one click


@pytest.mark.asyncio
async def test_shorten_rejects_non_http_url(client):
    async with client as c:
        resp = await c.post("/shorten", json={"url": "not a url"})
    assert resp.status_code == 422  # pydantic validation error


@pytest.mark.asyncio
async def test_redirect_unknown_code_is_404(client):
    async with client as c:
        resp = await c.get("/this-code-does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stats_unknown_code_is_404(client):
    async with client as c:
        resp = await c.get("/stats/this-code-does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_shorten_endpoint_enforces_rate_limit(client):
    async with client as c:
        statuses = []
        for i in range(settings.rate_limit_requests + 5):
            resp = await c.post("/shorten", json={"url": f"https://example.com/{i}"})
            statuses.append(resp.status_code)

    allowed = statuses.count(201)
    limited = statuses.count(429)
    assert allowed == settings.rate_limit_requests
    assert limited == 5
