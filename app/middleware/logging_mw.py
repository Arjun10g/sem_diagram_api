"""
app/middleware/logging_mw.py
============================
Request logging middleware. Records every request to PostgreSQL via
the non-blocking fire-and-forget API in app.db.database.

Also handles global exception catching — any unhandled exception that
escapes all route handlers is caught here, logged to the errors table,
and returned to the client as a clean 500 response with no stack trace.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db.database import log_error, log_request

logger = logging.getLogger("sem_api.requests")


def _client_ip(request: Request) -> str:
    for header in ("x-forwarded-for", "x-real-ip"):
        v = request.headers.get(header)
        if v:
            return v.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request to:
      1. The structured logger (stdout — appears in Railway logs)
      2. The PostgreSQL database (non-blocking)

    Catches any unhandled exception and:
      - Logs the full traceback to the errors table
      - Returns a clean 500 JSON response (no internal detail to client)
    """

    # Paths that generate too much noise if logged at INFO
    _SKIP_LOG = {"/health", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        ip    = _client_ip(request)
        path  = request.url.path
        method = request.method
        ua    = request.headers.get("user-agent", "")
        size  = request.headers.get("content-length")
        size_int = int(size) if size and size.isdigit() else None

        status_code = 500
        error_code: str | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code

            # Extract error_code from our JSON error responses
            if status_code >= 400:
                error_code = response.headers.get("x-error-code")

            return response

        except Exception as exc:
            tb_str = traceback.format_exc()
            error_code = "internal_error"

            # Log full details to DB
            log_error(
                error_type=type(exc).__name__,
                error_msg=str(exc),
                tb=tb_str,
                ip=ip,
                path=path,
            )

            # Log to stdout for Railway log streaming
            logger.error(
                "Unhandled exception on %s %s from %s: %s",
                method, path, ip, exc, exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "An unexpected error occurred. It has been logged.",
                },
            )

        finally:
            latency_ms = (time.monotonic() - start) * 1000

            # Structured stdout log
            if path not in self._SKIP_LOG:
                level = logging.WARNING if status_code >= 400 else logging.INFO
                logger.log(
                    level,
                    "%s %s %d %.1fms ip=%s",
                    method, path, status_code, latency_ms, ip,
                )

            # Non-blocking DB write
            log_request(
                ip=ip,
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                request_size=size_int,
                user_agent=ua,
                error_code=error_code,
            )
