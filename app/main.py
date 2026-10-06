from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import rate_limiter, shortener
from .config import settings
from .models import ShortenRequest, ShortenResponse, StatsResponse
from .redis_client import ping

app = FastAPI(title="URL Shortener & Rate Limiter")


def _client_id(request: Request) -> str:
    # In production behind a load balancer, this should read
    # X-Forwarded-For instead - request.client.host would just be the
    # load balancer's own IP for every request. Documented as a known
    # limitation in the README rather than silently wrong.
    return request.client.host if request.client else "unknown"


@app.get("/health")
async def health():
    try:
        redis_ok = await ping()
    except Exception:
        redis_ok = False
    return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok}


@app.post("/shorten", response_model=ShortenResponse, status_code=201)
async def shorten(req: ShortenRequest, request: Request):
    client_id = _client_id(request)
    if not await rate_limiter.is_allowed(client_id):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {settings.rate_limit_requests} "
                f"requests per {settings.rate_limit_window_seconds}s."
            ),
        )

    original_url = str(req.url)
    code = await shortener.create_short_code(original_url)
    return ShortenResponse(
        short_code=code,
        short_url=f"{settings.base_url}/{code}",
        original_url=original_url,
    )


@app.get("/stats/{code}", response_model=StatsResponse)
async def stats(code: str):
    original_url = await shortener.resolve_short_code(code)
    if original_url is None:
        raise HTTPException(status_code=404, detail="Short code not found.")
    clicks = await shortener.get_click_count(code)
    return StatsResponse(short_code=code, original_url=original_url, clicks=clicks)


@app.get("/{code}")
async def redirect(code: str, request: Request):
    client_id = _client_id(request)
    if not await rate_limiter.is_allowed(client_id):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {settings.rate_limit_requests} "
                f"requests per {settings.rate_limit_window_seconds}s."
            ),
        )

    original_url = await shortener.resolve_short_code(code)
    if original_url is None:
        raise HTTPException(status_code=404, detail="Short code not found.")
    await shortener.record_click(code)
    return RedirectResponse(url=original_url, status_code=307)
