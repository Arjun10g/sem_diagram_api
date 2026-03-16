"""
app/main.py
===========
FastAPI application entry point.

Middleware execution order (outermost → innermost on request):
  1. SecurityHeadersMiddleware  — hardening headers on every response
  2. RequestLoggingMiddleware   — log all requests + catch unhandled exceptions
  3. RateLimitMiddleware        — sliding window per IP/tier
  4. RequestSizeMiddleware      — reject oversized payloads
  5. TimeoutMiddleware          — kill runaway Graphviz renders
  6. AutoBanMiddleware          — temp-ban abusive IPs
  7. ConcurrencyLimitMiddleware — cap simultaneous renders
  8. CORSMiddleware             — innermost

Starlette evaluates middleware in REVERSE registration order.
"""

from __future__ import annotations

import os
import shutil

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.admin import router as admin_router
from app.db.database import close_db, init_db
from app.logger import configure_logging
from app.middleware.logging_mw import RequestLoggingMiddleware
from app.middleware.rate_limit import (
    ENABLED as RL_ENABLED,
    GLOBAL_RPM,
    PARSE_RPM,
    RENDER_RPM,
    RateLimitMiddleware,
)
from app.middleware.security import (
    AUTOBAN_BAN_SEC,
    AUTOBAN_ERROR_LIMIT,
    AUTOBAN_WINDOW_SEC,
    MAX_BODY_RENDER_BYTES,
    MAX_CONCURRENT_RENDERS,
    RENDER_TIMEOUT_SEC,
    AutoBanMiddleware,
    ConcurrencyLimitMiddleware,
    RequestSizeMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
)

# Configure structured logging before anything else
configure_logging()

import logging
logger = logging.getLogger("sem_api.main")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SEM Diagram API",
    description="Render lavaan SEM syntax to Graphviz path diagrams.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)

# ── Middleware (reverse registration order = reverse execution order) ─────────

app.add_middleware(ConcurrencyLimitMiddleware)   # 7
app.add_middleware(AutoBanMiddleware)            # 6
app.add_middleware(TimeoutMiddleware)            # 5
app.add_middleware(RequestSizeMiddleware)        # 4
app.add_middleware(RateLimitMiddleware)          # 3
app.add_middleware(RequestLoggingMiddleware)     # 2
app.add_middleware(SecurityHeadersMiddleware)    # 1

# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(router)
app.include_router(admin_router)

# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup() -> None:
    await init_db()

    dot_available = shutil.which("dot") is not None
    rl = "on" if RL_ENABLED else "OFF"

    logger.info(
        "SEM API started | graphviz=%s | rate_limit=%s "
        "render=%srpm parse=%srpm global=%srpm | "
        "max_body=%sB timeout=%ss concurrency=%s | "
        "autoban=%s_errors/%ss→%ss_ban | cors=%s",
        "✓" if dot_available else "✗ MISSING",
        rl, RENDER_RPM, PARSE_RPM, GLOBAL_RPM,
        MAX_BODY_RENDER_BYTES, RENDER_TIMEOUT_SEC, MAX_CONCURRENT_RENDERS,
        AUTOBAN_ERROR_LIMIT, AUTOBAN_WINDOW_SEC, AUTOBAN_BAN_SEC,
        _origins,
    )

    if not dot_available:
        logger.error(
            "Graphviz 'dot' binary not found — all render requests will fail. "
            "Install graphviz and ensure it is on PATH."
        )


@app.on_event("shutdown")
async def _shutdown() -> None:
    await close_db()
    logger.info("SEM API shutdown complete.")
