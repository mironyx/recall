"""OpenTelemetry initialisation (ADR-0011).

OTEL is wired via auto-instrumentation only. The exporter is off by default; if
``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset OTEL initialises in a no-op mode with
effectively zero runtime cost. Either way, trace_id and span_id are available
via :func:`get_trace_context` for structlog to bind onto each log line.

Phase 0 scope: only the no-op path is exercised. The export branch is a
placeholder for E4.2 — when implemented it will wire the OTLP exporter plus
auto-instrumentation for the HTTP listener, asyncpg, and outbound httpx.
"""

from __future__ import annotations

import os

import structlog
from opentelemetry import trace

_log = structlog.get_logger(__name__)

_INVALID_TRACE_ID = 0
_INVALID_SPAN_ID = 0


def configure_telemetry() -> None:
    """Initialise OTEL in no-op or export mode.

    Reads ``OTEL_EXPORTER_OTLP_ENDPOINT``. If unset, no provider is installed
    — :mod:`opentelemetry.trace` already returns a no-op tracer by default, so
    this is a cheap sanity check with no side effects. If set, the export
    branch (auto-instrumentation + OTLP exporter) would be wired; that code is
    out of scope for Phase 0 and will land in E4.2.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    # Export mode is wired in E4.2. Warn loudly so an operator who set the
    # variable expecting traces knows the branch is a Phase 0 placeholder.
    _log.warning(
        "otel_export_unimplemented",
        endpoint=endpoint,
        phase="phase-0",
        message=(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the export branch is not "
            "wired yet (lands in E4.2). Running in no-op mode."
        ),
    )


def get_trace_context() -> tuple[str, str]:
    """Extract current trace_id and span_id from the OTEL context.

    Returns a ``(trace_id, span_id)`` tuple. Both values are empty strings if
    no span is active (the typical case in Phase 0 with the exporter off).
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.trace_id == _INVALID_TRACE_ID or ctx.span_id == _INVALID_SPAN_ID:
        return ("", "")
    return (format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))
