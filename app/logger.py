"""
app/logger.py
=============
Configures Python's logging for the SEM API.

- JSON-style log lines when LOG_FORMAT=json (good for Railway log drain)
- Human-readable lines when LOG_FORMAT=text (default, good for local dev)
- Log level controlled by LOG_LEVEL env var (default INFO)

Call configure_logging() once at startup (done in main.py).
"""

from __future__ import annotations

import logging
import os
import sys
import time


LOG_LEVEL  = os.environ.get("LOG_LEVEL",  "INFO").upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").lower()


class _TextFormatter(logging.Formatter):
    _COLOURS = {
        logging.DEBUG:    "\033[36m",   # cyan
        logging.INFO:     "\033[32m",   # green
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[35m",   # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        ts    = time.strftime("%H:%M:%S", time.localtime(record.created))
        colour = self._COLOURS.get(record.levelno, "")
        level  = f"{colour}{record.levelname:8}{self._RESET}"
        name   = record.name.replace("sem_api.", "")
        msg    = super().format(record)
        return f"{ts} {level} [{name}] {record.getMessage()}"


class _JsonFormatter(logging.Formatter):
    import json as _json

    def format(self, record: logging.LogRecord) -> str:
        import json
        doc = {
            "ts":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "name":  record.name,
            "msg":   record.getMessage(),
        }
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return json.dumps(doc)


def configure_logging() -> None:
    """Set up root logger and named loggers. Call once at startup."""
    level = getattr(logging, LOG_LEVEL, logging.INFO)

    formatter: logging.Formatter
    if LOG_FORMAT == "json":
        formatter = _JsonFormatter()
    else:
        formatter = _TextFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure the sem_api namespace and suppress noisy third-party loggers
    root = logging.getLogger("sem_api")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    for noisy in ("uvicorn.access", "asyncpg"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Silence uvicorn's own access log (we produce our own)
    logging.getLogger("uvicorn.access").handlers = []
