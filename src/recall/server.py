"""Recall HTTP server — Starlette ASGI app with health endpoints.

Phase 0 mounts ``/healthz`` and ``/readyz`` on the ASGI app plus a request-
context middleware that binds ``request_id``/``trace_id``/``span_id`` into the
structlog contextvar at the transport boundary. The MCP Streamable HTTP
endpoint (ADR-0006) is mounted here in Phase 1.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import structlog
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from recall.health import healthz, readyz
from recall.logging import bind_request_context, unbind_request_context
from recall.telemetry import get_trace_context

_log = structlog.get_logger(__name__)


class RequestContextMiddleware:
    """ASGI middleware that binds request-scoped fields into the structlog context.

    On every HTTP request it generates a ``request_id``, extracts
    ``trace_id``/``span_id`` from the active OTEL context (empty strings in
    no-op mode), and binds all three via :func:`bind_request_context`. After
    the downstream app finishes — success or exception — the context is cleared
    so no leakage across requests.
    """

    def __init__(
        self,
        app: ASGIApp,
        request_id_factory: Callable[[], str] | None = None,
        trace_context_provider: Callable[[], tuple[str, str]] | None = None,
    ) -> None:
        self._app = app
        self._request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        self._trace_context_provider = trace_context_provider or get_trace_context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = self._request_id_factory()
        trace_id, span_id = self._trace_context_provider()
        bind_request_context(request_id=request_id, trace_id=trace_id, span_id=span_id)

        status_code = 500
        start = time.perf_counter()

        async def _send_with_status_capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, _send_with_status_capture)
            _log.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        finally:
            unbind_request_context()


def create_app(conn_string: str) -> Starlette:
    """Create the ASGI application.

    Mounts:
      * ``/healthz`` — liveness probe
      * ``/readyz``  — readiness probe, runs ``SELECT 1`` against ``conn_string``

    Installs :class:`RequestContextMiddleware` so every log line emitted while
    handling a request carries ``request_id``/``trace_id``/``span_id``.

    ``conn_string`` is stashed on ``app.state.conn_string`` so the health
    handlers can reach it without module-level state. A connection pool is
    intentionally *not* created here — Phase 0 opens a short-lived asyncpg
    connection per ``/readyz`` call (see `health.py`). When the MCP tool
    surface lands in Phase 1 the pool will be owned by its store.
    """
    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
        ],
        middleware=[Middleware(RequestContextMiddleware)],
    )
    app.state.conn_string = conn_string
    return app
