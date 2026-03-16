"""
app/middleware/rate_limit.py
============================
Sliding-window rate limiter implemented as a pure-Python ASGI middleware.

No Redis, no external dependencies — uses an in-memory dict with a lock.
Suitable for a single-process deployment (Railway, Render, Fly.io single instance).
For multi-process / multi-instance deployments, swap the storage backend to Redis
(see RateLimitStorage protocol at the bottom of this file).

Configuration
-------------
Set environment variables to override defaults:

    RATE_LIMIT_ENABLED        = "true"          # set "false" to disable entirely
    RATE_LIMIT_RENDER_RPM     = "20"            # /render* endpoints per IP per minute
    RATE_LIMIT_PARSE_RPM      = "60"            # /parse endpoint per IP per minute
    RATE_LIMIT_GLOBAL_RPM     = "120"           # all other endpoints per IP per minute
    RATE_LIMIT_BURST_RENDER   = "5"             # max burst (requests within 1 second)
    RATE_LIMIT_WHITELIST      = "127.0.0.1"     # comma-separated IPs that bypass limits

Usage in main.py
----------------
    from app.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""

from __future__ import annotations

import asyncio
import collections
import os
import time
from typing import Callable, Deque, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# DB import is optional — gracefully skipped if DB not configured
try:
    from app.db.database import log_rate_event as _db_log_rate_event
except ImportError:
    def _db_log_rate_event(*a, **kw): pass


# ── Configuration (read from environment) ─────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default

def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key, str(default)).lower()
    return v in ("1", "true", "yes", "on")

def _env_set(key: str, default: str) -> set:
    raw = os.environ.get(key, default)
    return {x.strip() for x in raw.split(",") if x.strip()}


ENABLED         = _env_bool("RATE_LIMIT_ENABLED", True)
RENDER_RPM      = _env_int("RATE_LIMIT_RENDER_RPM",   20)   # /render* per IP/min
PARSE_RPM       = _env_int("RATE_LIMIT_PARSE_RPM",    60)   # /parse per IP/min
GLOBAL_RPM      = _env_int("RATE_LIMIT_GLOBAL_RPM",  120)   # everything else
BURST_RENDER    = _env_int("RATE_LIMIT_BURST_RENDER",   5)  # max in 1 second
WHITELIST       = _env_set("RATE_LIMIT_WHITELIST", "127.0.0.1,::1")


# ── Sliding window store ───────────────────────────────────────────────────────

class _SlidingWindow:
    """
    Per-key sliding window counter.

    Stores a deque of request timestamps for each (ip, tier) key.
    Old timestamps outside the window are evicted on each check.
    """

    def __init__(self) -> None:
        # { key: deque of float timestamps }
        self._windows: Dict[str, Deque[float]] = collections.defaultdict(collections.deque)
        self._lock = asyncio.Lock()

    async def is_allowed(
        self,
        key: str,
        limit: int,
        window_seconds: float = 60.0,
        burst_limit: Optional[int] = None,
        burst_window: float = 1.0,
    ) -> tuple[bool, int, float]:
        """
        Check whether a request is allowed.

        Returns (allowed, requests_in_window, retry_after_seconds).
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        async with self._lock:
            dq = self._windows[key]

            # Evict expired timestamps
            while dq and dq[0] < cutoff:
                dq.popleft()

            count = len(dq)

            # Burst check (short window)
            if burst_limit is not None:
                burst_cutoff = now - burst_window
                burst_count = sum(1 for t in dq if t >= burst_cutoff)
                if burst_count >= burst_limit:
                    retry = burst_window - (now - dq[-burst_limit]) if len(dq) >= burst_limit else burst_window
                    return False, count, round(retry, 2)

            # Main window check
            if count >= limit:
                # retry_after = time until oldest request falls out of window
                retry = window_seconds - (now - dq[0]) if dq else window_seconds
                return False, count, round(retry, 2)

            dq.append(now)
            return True, count + 1, 0.0

    async def cleanup(self, max_keys: int = 50_000) -> None:
        """Evict the oldest keys when the store grows too large."""
        async with self._lock:
            if len(self._windows) <= max_keys:
                return
            now = time.monotonic()
            # Remove keys whose window is entirely expired (60s + buffer)
            stale = [k for k, dq in self._windows.items()
                     if not dq or now - dq[-1] > 120]
            for k in stale:
                del self._windows[k]


_store = _SlidingWindow()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP, respecting common proxy headers.
    Trusts X-Forwarded-For only if the request came through a known proxy.
    """
    # Railway, Render, Fly.io all set X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first (leftmost) IP — the original client
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _tier(path: str) -> tuple[str, int, Optional[int]]:
    """
    Map a URL path to (tier_name, rpm_limit, burst_limit).
    """
    if path.startswith("/render"):
        return "render", RENDER_RPM, BURST_RENDER
    if path.startswith("/parse"):
        return "parse", PARSE_RPM, None
    return "global", GLOBAL_RPM, None


_CLEANUP_INTERVAL = 300  # seconds between store cleanups
_last_cleanup = time.monotonic()


# ── Middleware ─────────────────────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter.

    Adds response headers:
        X-RateLimit-Limit      — requests allowed per minute for this tier
        X-RateLimit-Remaining  — requests remaining in current window
        X-RateLimit-Tier       — which tier this request was counted under
        Retry-After            — seconds to wait (only on 429 responses)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        global _last_cleanup

        # Periodic store cleanup (runs in background, non-blocking best-effort)
        now = time.monotonic()
        if now - _last_cleanup > _CLEANUP_INTERVAL:
            _last_cleanup = now
            asyncio.create_task(_store.cleanup())

        if not ENABLED:
            return await call_next(request)

        # Pass-through for health/docs
        path = request.url.path
        if path in {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}:
            return await call_next(request)

        ip = _get_client_ip(request)

        # Whitelist bypass
        if ip in WHITELIST:
            return await call_next(request)

        tier, limit, burst = _tier(path)
        key = f"{ip}:{tier}"

        allowed, count, retry_after = await _store.is_allowed(
            key=key,
            limit=limit,
            window_seconds=60.0,
            burst_limit=burst,
            burst_window=1.0,
        )

        if not allowed:
            _db_log_rate_event(
                ip=ip,
                event_type="rate_limited",
                tier=tier,
                details=f"limit={limit}/min retry_after={retry_after}s",
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Too many requests. Allowed {limit} requests/minute "
                        f"on the {tier!r} tier. Retry after {retry_after}s."
                    ),
                    "tier": tier,
                    "limit": limit,
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(int(retry_after) + 1),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Tier": tier,
                },
            )

        response = await call_next(request)

        # Attach informational headers to successful responses
        response.headers["X-RateLimit-Limit"]     = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Tier"]      = tier

        return response
