"""Structured logging configuration (ADR-0011).

All log output goes through structlog configured at startup. One JSON object per
line on stdout. Request-scoped fields (request_id, trace_id, span_id) are bound
to a contextvar at the transport boundary so every downstream log line carries
them automatically. Library logging (asyncpg, httpx, mcp SDK) is bridged into
structlog via the standard logging integration.
"""

from __future__ import annotations

import logging
import sys

import structlog

_REQUEST_CONTEXT_KEYS = ("request_id", "trace_id", "span_id")


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog as the sole logging path.

    Sets up the structlog processor chain (contextvars, level, timestamp, JSON),
    bridges stdlib logging into the same pipeline via ProcessorFormatter, and
    installs a single StreamHandler on the root logger so that all log output
    (structlog and stdlib alike) is emitted as JSON on stdout.

    Safe to call multiple times; existing handlers are replaced on each call so
    tests and reload scenarios do not duplicate output.
    """
    level = logging.getLevelName(log_level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp")

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


def bind_request_context(
    request_id: str,
    trace_id: str = "",
    span_id: str = "",
) -> None:
    """Bind request-scoped fields to the structlog contextvar.

    Called at the transport boundary when a request arrives. After this call
    every log line emitted on the same task inherits these fields.
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        trace_id=trace_id,
        span_id=span_id,
    )


def unbind_request_context() -> None:
    """Clear request-scoped fields after a request completes."""
    structlog.contextvars.unbind_contextvars(*_REQUEST_CONTEXT_KEYS)
