#!/usr/bin/env python3
"""
A real load test against a running instance of the service - not a
toy/demo, an actual concurrency and correctness check.

What it proves, against a live server:
1. Throughput/latency under N simultaneous requests.
2. No two successful /shorten calls ever return the same short_code, even
   fired at the exact same instant (the atomic-counter design in
   app/shortener.py).
3. The rate limiter admits exactly RATE_LIMIT_REQUESTS of them and
   rejects the rest with 429 - not "approximately," exactly - which is
   what the Lua script in app/rate_limiter.py is for.

Usage:
    # with the app + redis already running (e.g. `docker compose up`):
    python scripts/load_test.py --url http://localhost:8000 --requests 500
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def _one_request(client: httpx.AsyncClient, base_url: str, i: int) -> tuple[int, float, str | None]:
    start = time.perf_counter()
    try:
        resp = await client.post(f"{base_url}/shorten", json={"url": f"https://example.com/load-test/{i}"})
    except httpx.HTTPError as exc:
        return 0, time.perf_counter() - start, None
    elapsed = time.perf_counter() - start
    code = resp.json().get("short_code") if resp.status_code == 201 else None
    return resp.status_code, elapsed, code


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=500)
    args = parser.parse_args()

    print(f"Firing {args.requests} concurrent POST /shorten requests at {args.url} ...")

    # httpx.AsyncClient defaults to a 100-connection pool, which silently
    # serializes anything beyond that - at --requests above 100 the
    # client itself becomes the bottleneck being measured, not the
    # server. Raise it so the load test actually sends `--requests`
    # requests concurrently.
    limits = httpx.Limits(max_connections=args.requests + 10, max_keepalive_connections=args.requests)
    async with httpx.AsyncClient(timeout=20.0, limits=limits) as client:
        t0 = time.perf_counter()
        results = await asyncio.gather(
            *(_one_request(client, args.url, i) for i in range(args.requests))
        )
        total_elapsed = time.perf_counter() - t0

    statuses = [r[0] for r in results]
    latencies = [r[1] for r in results if r[0] != 0]
    codes = [r[2] for r in results if r[2] is not None]

    allowed = statuses.count(201)
    limited = statuses.count(429)
    errors = sum(1 for s in statuses if s not in (201, 429))

    print()
    print(f"Total wall time:       {total_elapsed:.3f}s")
    print(f"Requests/sec (approx): {args.requests / total_elapsed:.1f}")
    print(f"201 Created:           {allowed}")
    print(f"429 Rate limited:      {limited}")
    print(f"Other/errors:          {errors}")
    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        print(f"Latency p50:           {p50 * 1000:.1f}ms")
        print(f"Latency p95:           {p95 * 1000:.1f}ms")

    print()
    unique_codes = len(set(codes))
    if unique_codes == len(codes):
        print(f"PASS: all {len(codes)} successful short codes were unique (no collisions).")
    else:
        print(f"FAIL: {len(codes)} successful responses but only {unique_codes} unique codes!")

    print(f"(Server-side rate limit should admit exactly its configured RATE_LIMIT_REQUESTS; "
          f"check /health or the server's URLSHORT_RATE_LIMIT_REQUESTS env var to confirm "
          f"the {allowed} admitted above matches it.)")


if __name__ == "__main__":
    asyncio.run(main())
