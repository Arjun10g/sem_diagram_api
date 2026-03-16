"""
app/db/database.py
==================
Async PostgreSQL database layer for structured API activity logging.

Tables
------
  requests    — every API call: IP, endpoint, method, status, latency
  errors      — unhandled exceptions with traceback and context
  rate_events — rate-limit hits, auto-bans, ban lifts

Connection
----------
Set DATABASE_URL in the environment (populated automatically on Railway):
    DATABASE_URL=postgresql://user:pass@host:5432/dbname

All writes are fire-and-forget (non-blocking) so the database never
slows down an API response. Reads serve the /admin/stats endpoint only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from datetime import timedelta
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("sem_api.db")

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Max rows per table before oldest records are pruned
MAX_REQUESTS_ROWS = int(os.environ.get("DB_MAX_REQUESTS", 500_000))
MAX_ERRORS_ROWS   = int(os.environ.get("DB_MAX_ERRORS",    50_000))
MAX_EVENTS_ROWS   = int(os.environ.get("DB_MAX_EVENTS",   200_000))

PRUNE_INTERVAL = int(os.environ.get("DB_PRUNE_INTERVAL", 1_000))

_pool: Optional[asyncpg.Pool] = None
_insert_count = 0


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip           TEXT        NOT NULL,
    method       TEXT        NOT NULL,
    path         TEXT        NOT NULL,
    status_code  INTEGER     NOT NULL,
    latency_ms   NUMERIC(10,2),
    request_size INTEGER,
    user_agent   TEXT,
    error_code   TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip           TEXT,
    path         TEXT,
    error_type   TEXT        NOT NULL,
    error_msg    TEXT        NOT NULL,
    traceback    TEXT,
    request_body TEXT
);

CREATE TABLE IF NOT EXISTS rate_events (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip           TEXT        NOT NULL,
    event_type   TEXT        NOT NULL,
    tier         TEXT,
    details      TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_ts     ON requests   (ts DESC);
CREATE INDEX IF NOT EXISTS idx_requests_ip     ON requests   (ip);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests   (status_code);
CREATE INDEX IF NOT EXISTS idx_errors_ts       ON errors     (ts DESC);
CREATE INDEX IF NOT EXISTS idx_errors_ip       ON errors     (ip);
CREATE INDEX IF NOT EXISTS idx_events_ts       ON rate_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_ip       ON rate_events (ip);
"""


# ── Pool lifecycle ────────────────────────────────────────────────────────────

async def init_db() -> None:
    """
    Create the connection pool and run schema migrations.
    Called once at application startup.
    Logs a warning and continues gracefully if DATABASE_URL is not set
    so the API still works without a database in local dev.
    """
    global _pool

    if not DATABASE_URL:
        logger.warning(
            "DATABASE_URL is not set — request logging disabled. "
            "Set DATABASE_URL to enable the PostgreSQL database."
        )
        return

    try:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=10,
            ssl="require" if "railway" in DATABASE_URL.lower() else None,
        )
        # Use an advisory lock so only one worker runs migrations at a time
        # when multiple uvicorn workers start simultaneously.
        async with _pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(8675309)")
            try:
                await conn.execute(_SCHEMA)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(8675309)")
        logger.info("Database connection pool established (%s)", _safe_url(DATABASE_URL))
    except Exception as exc:
        logger.error("Failed to connect to database: %s — logging disabled", exc)
        _pool = None


async def close_db() -> None:
    """Close the connection pool gracefully on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def _safe_url(url: str) -> str:
    """Redact password from a database URL for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        safe = p._replace(netloc=f"{p.username}:***@{p.hostname}:{p.port}")
        return urlunparse(safe)
    except Exception:
        return "***"


# ── Fire-and-forget writer ────────────────────────────────────────────────────

def _fire(coro) -> None:
    """Schedule a coroutine without blocking. DB writes must never crash requests."""
    if _pool is None:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
        else:
            loop.run_until_complete(coro)
    except Exception:
        pass


# ── Async write implementations ───────────────────────────────────────────────

async def _write_request(
    ip: str, method: str, path: str, status_code: int,
    latency_ms: float, request_size: Optional[int],
    user_agent: Optional[str], error_code: Optional[str],
) -> None:
    global _insert_count
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO requests
                   (ip, method, path, status_code, latency_ms,
                    request_size, user_agent, error_code)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                ip, method, path, status_code,
                round(latency_ms, 2), request_size,
                (user_agent or "")[:512], error_code,
            )
        _insert_count += 1
        if _insert_count % PRUNE_INTERVAL == 0:
            asyncio.create_task(_prune())
    except Exception as exc:
        logger.debug("DB write_request failed: %s", exc)


async def _write_error(
    error_type: str, error_msg: str,
    tb: Optional[str], ip: Optional[str],
    path: Optional[str], request_body: Optional[str],
) -> None:
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO errors
                   (ip, path, error_type, error_msg, traceback, request_body)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                ip, path,
                error_type[:200],
                error_msg[:2000],
                (tb or "")[:5000],
                (request_body or "")[:500],
            )
    except Exception as exc:
        logger.debug("DB write_error failed: %s", exc)


async def _write_rate_event(
    ip: str, event_type: str,
    tier: Optional[str], details: Optional[str],
) -> None:
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rate_events (ip, event_type, tier, details)
                   VALUES ($1,$2,$3,$4)""",
                ip, event_type, tier, details,
            )
    except Exception as exc:
        logger.debug("DB write_rate_event failed: %s", exc)


async def _prune() -> None:
    """Delete oldest rows when tables exceed configured max sizes."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            for table, max_rows in [
                ("requests",    MAX_REQUESTS_ROWS),
                ("errors",      MAX_ERRORS_ROWS),
                ("rate_events", MAX_EVENTS_ROWS),
            ]:
                await conn.execute(f"""
                    DELETE FROM {table}
                    WHERE id IN (
                        SELECT id FROM {table}
                        ORDER BY id ASC
                        LIMIT GREATEST(0,
                            (SELECT COUNT(*) FROM {table}) - {max_rows}
                        )
                    )
                """)
    except Exception as exc:
        logger.debug("DB prune failed: %s", exc)


# ── Public non-blocking API ───────────────────────────────────────────────────

def log_request(
    ip: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    request_size: Optional[int] = None,
    user_agent: Optional[str] = None,
    error_code: Optional[str] = None,
) -> None:
    """Log every API request. Non-blocking — safe to call from middleware."""
    _fire(_write_request(
        ip, method, path, status_code,
        latency_ms, request_size, user_agent, error_code,
    ))


def log_error(
    error_type: str,
    error_msg: str,
    tb: Optional[str] = None,
    ip: Optional[str] = None,
    path: Optional[str] = None,
    request_body: Optional[str] = None,
) -> None:
    """Log an unhandled exception. Non-blocking."""
    _fire(_write_error(error_type, error_msg, tb, ip, path, request_body))


def log_rate_event(
    ip: str,
    event_type: str,
    tier: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Log a rate-limit hit or auto-ban event. Non-blocking."""
    _fire(_write_rate_event(ip, event_type, tier, details))


# ── Read API (used by /admin/stats) ───────────────────────────────────────────

async def get_stats(hours: int = 24) -> Dict[str, Any]:
    """Return summary statistics for the last N hours."""
    if _pool is None:
        return {"error": "database_not_connected"}

    async with _pool.acquire() as conn:

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM requests WHERE ts >= NOW() - $1::interval",
            timedelta(hours=hours),
        )

        by_status = await conn.fetch("""
            SELECT
                CASE
                    WHEN status_code < 300 THEN '2xx'
                    WHEN status_code < 400 THEN '3xx'
                    WHEN status_code < 500 THEN '4xx'
                    ELSE '5xx'
                END AS cls,
                COUNT(*) AS n
            FROM requests
            WHERE ts >= NOW() - $1::interval
            GROUP BY cls
        """, timedelta(hours=hours))

        top_endpoints = await conn.fetch("""
            SELECT path, COUNT(*) AS n,
                   ROUND(AVG(latency_ms)::numeric, 1) AS avg_ms
            FROM requests
            WHERE ts >= NOW() - $1::interval
            GROUP BY path ORDER BY n DESC LIMIT 10
        """, timedelta(hours=hours))

        top_ips = await conn.fetch("""
            SELECT ip, COUNT(*) AS n
            FROM requests
            WHERE ts >= NOW() - $1::interval
            GROUP BY ip ORDER BY n DESC LIMIT 10
        """, timedelta(hours=hours))

        error_count = await conn.fetchval(
            "SELECT COUNT(*) FROM errors WHERE ts >= NOW() - $1::interval",
            timedelta(hours=hours),
        )

        recent_errors = await conn.fetch("""
            SELECT ts, ip, path, error_type, LEFT(error_msg, 200) AS error_msg
            FROM errors
            WHERE ts >= NOW() - $1::interval
            ORDER BY ts DESC LIMIT 20
        """, timedelta(hours=hours))

        rate_events = await conn.fetch("""
            SELECT event_type, COUNT(*) AS n
            FROM rate_events
            WHERE ts >= NOW() - $1::interval
            GROUP BY event_type
        """, timedelta(hours=hours))

        recent_bans = await conn.fetch("""
            SELECT ts, ip, details
            FROM rate_events
            WHERE ts >= NOW() - $1::interval AND event_type = 'auto_banned'
            ORDER BY ts DESC LIMIT 10
        """, timedelta(hours=hours))

        render_latencies = await conn.fetch("""
            SELECT latency_ms
            FROM requests
            WHERE ts >= NOW() - $1::interval
              AND path LIKE '/render%'
              AND status_code < 400
              AND latency_ms IS NOT NULL
            ORDER BY latency_ms
        """, timedelta(hours=hours))

        latencies: List[float] = [float(r["latency_ms"]) for r in render_latencies]
        p50 = latencies[len(latencies) // 2]       if latencies else None
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else None

    return {
        "window_hours": hours,
        "total_requests": total,
        "by_status_class": {r["cls"]: r["n"] for r in by_status},
        "top_endpoints": [
            {"path": r["path"], "requests": r["n"], "avg_latency_ms": float(r["avg_ms"] or 0)}
            for r in top_endpoints
        ],
        "top_ips": [{"ip": r["ip"], "requests": r["n"]} for r in top_ips],
        "error_count": error_count,
        "recent_errors": [dict(r) for r in recent_errors],
        "rate_events": {r["event_type"]: r["n"] for r in rate_events},
        "recent_bans": [dict(r) for r in recent_bans],
        "render_latency": {
            "p50_ms": round(p50, 1) if p50 else None,
            "p95_ms": round(p95, 1) if p95 else None,
            "sample_size": len(latencies),
        },
    }
