# URL Shortener & Rate Limiter — Built for Scale

A URL shortener with a built-in, distributed rate limiter — the two
problems most commonly asked about in backend system-design interviews,
actually built, tested under real concurrency, and verified running on
GitHub Actions rather than just written.

**This is a portfolio / learning project.**

## What it does

- `POST /shorten` — take a long URL, return a short code.
- `GET /{code}` — redirect to the original URL, tracking a click.
- `GET /stats/{code}` — see how many times a short code has been visited.
- Every endpoint that creates load (`/shorten`, the redirect) is behind a
  per-client rate limiter: too many requests in the configured time
  window get a `429 Too Many Requests`, not silently queued or dropped.

## Why Redis, in plain terms

Redis is an in-memory key-value store — like a dictionary that lives in
RAM instead of on disk, shared across every process that connects to it,
answering in well under a millisecond. It's not a replacement for a real
database; it's the standard tool for the specific things this app needs
on *every single request*: handing out a unique short code, and checking
"has this client made too many requests recently?" Both need an answer
instantly, which is exactly what Redis is built for.

## The two design decisions this project is actually about

**1. Short codes come from an atomic counter, not random-and-retry.**
`Redis INCR` is atomic — Redis runs every command on a single thread, so
even if 1,000 requests hit `/shorten` in the same instant, each one gets
a different, sequential number back. No two requests can ever receive the
same number, so no collision is even *possible* — there's no
generate-check-retry loop needed, which is what the more obvious
"random 6-character code" approach requires, and that approach gets
slower exactly as the number of stored URLs grows. See
`app/shortener.py` and `tests/test_shortener.py::test_concurrent_short_code_creation_never_collides`,
which fires 200 concurrent creations and asserts all 200 codes are
unique.

**2. The rate limiter is a sliding window, enforced atomically via a Lua
script.** The algorithm itself (sliding window over a Redis sorted set)
is simple. The part that actually matters is *why it has to run as one
atomic Lua script instead of three separate Redis calls*: picture two
requests arriving at the same instant, both under a limit of 5 — both
read "4 so far," both decide "allowed," both get added, and the client
has now made 6 requests despite the limit being 5. A Lua script runs as a
single, uninterruptible unit on Redis's single thread, which closes that
race. `tests/test_rate_limiter.py::test_concurrent_requests_never_exceed_the_limit`
fires 3x the limit's worth of requests all at once via `asyncio.gather`
and asserts *exactly* the configured limit got through — not
"approximately."

## How this actually scales (not just "uses Redis")

The app itself keeps zero state in memory — every short code, click
count, and rate-limit window lives in Redis. That's what makes it
horizontally scalable in the way the project's name claims: you could run
10 copies of this app behind a load balancer, and they'd all share the
same counter (no two instances could ever hand out the same short code)
and the same rate limits (a client can't dodge the limit by getting
load-balanced to a different instance). The app being stateless is the
actual scaling story — Redis is what makes statelessness possible without
losing correctness.

## Load test (real numbers, not estimated)

`scripts/load_test.py` fires concurrent `POST /shorten` requests at a
running instance and reports throughput, latency, and whether any short
codes collided. Run against this project's single-process dev server
(`uvicorn`, no extra workers) on ordinary hardware:

| Concurrent requests | Requests/sec | p50 latency | p95 latency | Errors | Code collisions |
|---|---|---|---|---|---|
| 100 | 325 | 156ms | 240ms | 0 | 0 |
| 200 | 178 | 433ms | 991ms | 0 | 0 |

Latency rises as concurrency increases past what one single-process dev
server can handle — expected, and the reason production deployments run
multiple app instances behind a load balancer rather than one process.
Because all correctness (no collisions, exact rate-limit enforcement)
lives in Redis rather than in-process memory, adding more app instances
is a direct, safe way to raise that throughput ceiling, not a source of
new bugs. Reproduce it yourself:

```bash
docker compose up -d
python scripts/load_test.py --url http://localhost:8000 --requests 200
```

## Running it locally

**With Docker (recommended — gives you Redis too):**

```bash
docker compose up
```

Then `curl -X POST localhost:8000/shorten -d '{"url":"https://example.com"}' -H 'Content-Type: application/json'`.

**Without Docker** (needs a local Redis running):

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
redis-server --daemonize yes
uvicorn app.main:app --reload
```

## Running the tests

```bash
pip install -r requirements-dev.txt
redis-server --daemonize yes   # or: docker run -d -p 6379:6379 redis:7-alpine
pytest tests/ -v
```

16 tests, including the two concurrency tests described above. All run
against a real Redis instance — nothing about the atomicity claims this
project makes is mocked.

## CI/CD

`.github/workflows/ci.yml` runs the full test suite against a real
`redis:7-alpine` service container on every push/PR to `main` (not a
mock), then builds the Docker image. A broken rate limiter or a
short-code collision would fail CI, the same way the concurrency tests
catch it locally.

## Project structure

```
url-shortener/
├── app/
│   ├── main.py             # FastAPI routes
│   ├── shortener.py        # atomic-counter short-code generation
│   ├── rate_limiter.py     # Lua-script sliding-window rate limiter
│   ├── redis_client.py     # shared async Redis connection
│   ├── config.py           # settings (env-var driven)
│   └── models.py           # request/response schemas
├── tests/                  # 16 tests incl. real concurrency tests
├── scripts/load_test.py    # real concurrent load test against a live instance
├── Dockerfile
├── docker-compose.yml       # app + redis, one command to run both
└── .github/workflows/ci.yml
```

## Tech stack

Python, FastAPI, Redis (atomic counters, Lua scripting, sorted sets),
Docker, Docker Compose, GitHub Actions, pytest + pytest-asyncio.
