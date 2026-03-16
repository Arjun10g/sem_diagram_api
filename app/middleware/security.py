"""
app/middleware/security.py
==========================
Multi-layer security middleware stack for the SEM Diagram API.

Layers (applied in order, outermost first):
  1. SecurityHeadersMiddleware  — sets hardening response headers on every reply
  2. RequestSizeMiddleware      — rejects bodies over a configurable byte limit
  3. TimeoutMiddleware          — kills requests that take too long (Graphviz runaway)
  4. AutoBanMiddleware          — tracks repeated errors per IP and temporarily bans
  5. ConcurrencyLimitMiddleware — caps simultaneous in-flight render requests

All limits are configurable via environment variables (see CONFIG section).
All middleware is pure-Python / pure-asyncio — no extra packages required.

Installation in main.py (order matters — add in reverse execution order):
    app.add_middleware(ConcurrencyLimitMiddleware)
    app.add_middleware(AutoBanMiddleware)
    app.add_middleware(TimeoutMiddleware)
    app.add_middleware(RequestSizeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)   # already present
"""

from __future__ import annotations

import asyncio
import collections
import os
import time
from typing import Callable, Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

try:
    from app.db.database import log_rate_event as _db_log_rate_event
except ImportError:
    def _db_log_rate_event(*a, **kw): pass


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def _ei(k: str, d: int) -> int:
    try: return int(os.environ.get(k, d))
    except (ValueError, TypeError): return d

def _ef(k: str, d: float) -> float:
    try: return float(os.environ.get(k, d))
    except (ValueError, TypeError): return d

def _eb(k: str, d: bool) -> bool:
    return os.environ.get(k, str(d)).lower() in ("1","true","yes","on")

def _es(k: str, d: str) -> set:
    return {x.strip() for x in os.environ.get(k, d).split(",") if x.strip()}


# Request size
MAX_BODY_BYTES        = _ei("MAX_BODY_BYTES",        64_000)  # 64 KB default

# Per-endpoint size overrides (bytes)
MAX_BODY_RENDER_BYTES = _ei("MAX_BODY_RENDER_BYTES", 32_000)  # 32 KB for render
MAX_BODY_PARSE_BYTES  = _ei("MAX_BODY_PARSE_BYTES",  32_000)

# Timeout
RENDER_TIMEOUT_SEC    = _ef("RENDER_TIMEOUT_SEC",    25.0)   # Graphviz hard limit
PARSE_TIMEOUT_SEC     = _ef("PARSE_TIMEOUT_SEC",     10.0)
GLOBAL_TIMEOUT_SEC    = _ef("GLOBAL_TIMEOUT_SEC",    15.0)

# Auto-ban
AUTOBAN_ENABLED       = _eb("AUTOBAN_ENABLED",       True)
AUTOBAN_ERROR_LIMIT   = _ei("AUTOBAN_ERROR_LIMIT",   30)    # errors within window
AUTOBAN_WINDOW_SEC    = _ei("AUTOBAN_WINDOW_SEC",    60)    # sliding window
AUTOBAN_BAN_SEC       = _ei("AUTOBAN_BAN_SEC",       300)   # 5-minute ban
AUTOBAN_WHITELIST     = _es("AUTOBAN_WHITELIST",     "127.0.0.1,::1")

# Concurrency
MAX_CONCURRENT_RENDERS = _ei("MAX_CONCURRENT_RENDERS", 10)  # simultaneous Graphviz processes

# Security headers
HSTS_MAX_AGE          = _ei("HSTS_MAX_AGE",          31_536_000)  # 1 year
ALLOWED_HOSTS         = _es("ALLOWED_HOSTS",          "")   # empty = allow all


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _client_ip(request: Request) -> str:
    for header in ("x-forwarded-for", "x-real-ip"):
        v = request.headers.get(header)
        if v:
            return v.split(",")[0].strip()
    return (request.client.host if request.client else "unknown")


def _json_error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "message": message, **extra},
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. SECURITY HEADERS
# ══════════════════════════════════════════════════════════════════════════════

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds hardening headers to every response.

    Headers set:
        X-Content-Type-Options  — prevents MIME sniffing
        X-Frame-Options         — prevents clickjacking
        X-XSS-Protection        — legacy XSS filter hint
        Referrer-Policy         — limits referrer leakage
        Content-Security-Policy — restricts what browsers can load
        Strict-Transport-Security — HTTPS enforcement (omitted on localhost)
        Permissions-Policy      — disables unused browser features
        Cache-Control           — API responses should not be cached by proxies
    """

    _CSP = (
        "default-src 'none'; "
        "frame-ancestors 'none';"
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"]  = "nosniff"
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["X-XSS-Protection"]        = "1; mode=block"
        response.headers["Referrer-Policy"]         = "no-referrer"
        response.headers["Content-Security-Policy"] = self._CSP
        response.headers["Permissions-Policy"]      = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

        # HSTS only on HTTPS (not localhost)
        host = request.headers.get("host", "")
        if not any(h in host for h in ("localhost", "127.0.0.1", "::1")):
            response.headers["Strict-Transport-Security"] = (
                f"max-age={HSTS_MAX_AGE}; includeSubDomains"
            )

        # Remove headers that leak server info
        for h in ("server", "x-powered-by"):
            if h in response.headers:
                del response.headers[h]

        return response


# ══════════════════════════════════════════════════════════════════════════════
# 2. REQUEST SIZE LIMIT
# ══════════════════════════════════════════════════════════════════════════════

class RequestSizeMiddleware(BaseHTTPMiddleware):
    """
    Rejects request bodies over a per-endpoint size limit.

    Protects against:
    - Oversized JSON payloads designed to exhaust memory during parsing
    - Huge lavaan syntax strings that would produce enormous DOT graphs

    Checks Content-Length header first (fast path), then reads actual bytes
    for chunked transfers without a Content-Length.
    """

    def _limit_for(self, path: str) -> int:
        if path.startswith("/render"): return MAX_BODY_RENDER_BYTES
        if path.startswith("/parse"):  return MAX_BODY_PARSE_BYTES
        return MAX_BODY_BYTES

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path  = request.url.path
        limit = self._limit_for(path)

        # Fast path: Content-Length header — check before reading body
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    return _json_error(
                        413, "payload_too_large",
                        f"Request body exceeds the {limit:,} byte limit for this endpoint.",
                        limit_bytes=limit,
                    )
            except ValueError:
                pass  # malformed header — Pydantic will reject downstream

        # Read and cache the full body via request.body().
        # This stores it in request._body so every downstream handler
        # (FastAPI, Pydantic, other middleware) can read it normally.
        # This is the correct pattern for BaseHTTPMiddleware body inspection.
        body = await request.body()
        if len(body) > limit:
            return _json_error(
                413, "payload_too_large",
                f"Request body exceeds the {limit:,} byte limit for this endpoint.",
                limit_bytes=limit,
            )

        return await call_next(request)


# ══════════════════════════════════════════════════════════════════════════════
# 3. TIMEOUT
# ══════════════════════════════════════════════════════════════════════════════

class TimeoutMiddleware(BaseHTTPMiddleware):
    """
    Enforces a hard timeout on every request.

    Graphviz can occasionally enter long computation loops on pathological
    SEM models (highly connected graphs, many constraints). Without a timeout
    a single bad request can block the event loop or exhaust worker threads.

    On timeout: returns 504 Gateway Timeout with a clear message.
    """

    def _timeout_for(self, path: str) -> float:
        if path.startswith("/render"): return RENDER_TIMEOUT_SEC
        if path.startswith("/parse"):  return PARSE_TIMEOUT_SEC
        return GLOBAL_TIMEOUT_SEC

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        timeout = self._timeout_for(request.url.path)
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except asyncio.TimeoutError:
            return _json_error(
                504, "request_timeout",
                f"Request exceeded the {timeout}s time limit. "
                "Try simplifying your model or reducing the number of variables.",
                timeout_seconds=timeout,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 4. AUTO-BAN
# ══════════════════════════════════════════════════════════════════════════════

class _BanStore:
    """Tracks error counts and bans per IP."""

    def __init__(self) -> None:
        # { ip: deque of error timestamps }
        self._errors: Dict[str, Deque[float]] = collections.defaultdict(collections.deque)
        # { ip: ban_expiry_timestamp }
        self._bans: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def is_banned(self, ip: str) -> tuple[bool, float]:
        """Returns (is_banned, seconds_remaining)."""
        async with self._lock:
            expiry = self._bans.get(ip)
            if expiry is None:
                return False, 0.0
            remaining = expiry - time.monotonic()
            if remaining <= 0:
                del self._bans[ip]
                return False, 0.0
            return True, round(remaining, 1)

    async def record_error(self, ip: str, status: int) -> bool:
        """
        Record a 4xx/5xx response for this IP.
        Returns True if the IP was just banned.
        """
        # Only track errors that indicate probing / abuse
        # 422: malformed requests (fuzzing)
        # 400: bad requests
        # 429: already rate-limited but still hammering
        # 413: oversized payloads
        if status not in {400, 413, 422, 429, 500}:
            return False

        now = time.monotonic()
        cutoff = now - AUTOBAN_WINDOW_SEC

        async with self._lock:
            dq = self._errors[ip]
            while dq and dq[0] < cutoff:
                dq.popleft()
            dq.append(now)

            if len(dq) >= AUTOBAN_ERROR_LIMIT and ip not in self._bans:
                self._bans[ip] = now + AUTOBAN_BAN_SEC
                return True
        return False

    async def cleanup(self) -> None:
        now = time.monotonic()
        async with self._lock:
            expired_bans = [ip for ip, exp in self._bans.items() if exp <= now]
            for ip in expired_bans:
                del self._bans[ip]
            stale_errors = [ip for ip, dq in self._errors.items()
                            if not dq or now - dq[-1] > AUTOBAN_WINDOW_SEC * 2]
            for ip in stale_errors:
                del self._errors[ip]


_ban_store = _BanStore()
_ban_last_cleanup = time.monotonic()


class AutoBanMiddleware(BaseHTTPMiddleware):
    """
    Automatically bans IPs that trigger too many errors in a short window.

    Protects against:
    - Fuzzing / scanning (streams of 422 malformed requests)
    - Persistent rate-limit abusers (keeps hitting after 429)
    - Oversized payload probing

    An IP accumulating AUTOBAN_ERROR_LIMIT errors within AUTOBAN_WINDOW_SEC
    seconds is banned for AUTOBAN_BAN_SEC seconds.  Default: 30 errors/minute
    → 5-minute ban.

    Banned IPs receive 403 Forbidden with the ban expiry time.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        global _ban_last_cleanup

        # Periodic cleanup
        now = time.monotonic()
        if now - _ban_last_cleanup > 120:
            _ban_last_cleanup = now
            asyncio.create_task(_ban_store.cleanup())

        if not AUTOBAN_ENABLED:
            return await call_next(request)

        ip = _client_ip(request)
        if ip in AUTOBAN_WHITELIST:
            return await call_next(request)

        # Check if already banned
        banned, remaining = await _ban_store.is_banned(ip)
        if banned:
            _db_log_rate_event(
                ip=ip,
                event_type="ban_rejected",
                details=f"remaining={remaining}s path={request.url.path}",
            )
            return _json_error(
                403, "ip_banned",
                f"Your IP has been temporarily banned due to excessive errors. "
                f"Try again in {remaining}s.",
                retry_after=remaining,
            )

        response = await call_next(request)

        # Record errors after the fact
        newly_banned = await _ban_store.record_error(ip, response.status_code)
        if newly_banned:
            import logging
            logging.getLogger("sem_api.autoban").warning(
                "Banned IP %s for %ds after %d errors in %ds window",
                ip, AUTOBAN_BAN_SEC, AUTOBAN_ERROR_LIMIT, AUTOBAN_WINDOW_SEC,
            )
            _db_log_rate_event(
                ip=ip,
                event_type="auto_banned",
                details=f"banned_for={AUTOBAN_BAN_SEC}s errors_in_window={AUTOBAN_ERROR_LIMIT}",
            )

        return response


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONCURRENCY LIMIT
# ══════════════════════════════════════════════════════════════════════════════

_render_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """
    Caps the number of simultaneous render requests.

    Graphviz is CPU-bound. Allowing unlimited concurrent renders means a
    burst of 50 simultaneous requests would spawn 50 processes, saturate
    the CPU, and cause all of them to time out.

    Non-render endpoints are not throttled by this middleware — they are
    fast (parse is pure Python, health/examples are trivial).

    When the semaphore is exhausted: 503 Service Unavailable with a
    clear message. The Shiny app's safe_svg/safe_render wrappers will
    catch this and show it in the diagnostics panel.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not request.url.path.startswith("/render"):
            return await call_next(request)

        acquired = _render_semaphore._value > 0  # non-blocking peek
        if not acquired and _render_semaphore.locked():
            return _json_error(
                503, "server_busy",
                f"The server is currently processing the maximum number of "
                f"render requests ({MAX_CONCURRENT_RENDERS}). "
                "Please retry in a moment.",
                max_concurrent=MAX_CONCURRENT_RENDERS,
            )

        async with _render_semaphore:
            return await call_next(request)
