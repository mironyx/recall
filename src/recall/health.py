"""Health check endpoints (Story 6.3).

``/healthz`` is a liveness probe — always 200 if the process is alive.
``/readyz`` is a readiness probe — 200 when the database is reachable, 503
otherwise. Both must respond well under one second.
"""

from __future__ import annotations

import asyncio

import asyncpg  # type: ignore[import-untyped]
import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse

# Combined connect + query budget must stay inside the 1 s health-endpoint SLA
# (LLD I7). Split: 0.5 s to establish the connection, 0.3 s to run SELECT 1.
_READYZ_CONNECT_TIMEOUT_SECONDS = 0.5
_READYZ_QUERY_TIMEOUT_SECONDS = 0.3

log = structlog.get_logger(__name__)


async def healthz(request: Request) -> JSONResponse:
    """Liveness probe. Always returns 200 with ``{"status": "ok"}``."""
    del request
    return JSONResponse({"status": "ok"})


async def readyz(request: Request) -> JSONResponse:
    """Readiness probe.

    Opens a short-lived asyncpg connection to ``app.state.conn_string`` and
    runs ``SELECT 1``. Returns 200 ``{"status": "ready"}`` on success and
    503 ``{"status": "not_ready", "reason": ...}`` on failure or timeout.
    """
    conn_string: str = request.app.state.conn_string
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(conn_string, timeout=_READYZ_CONNECT_TIMEOUT_SECONDS),
            timeout=_READYZ_CONNECT_TIMEOUT_SECONDS,
        )
    except (TimeoutError, OSError, asyncpg.PostgresError) as exc:
        log.warning("readyz_db_unreachable", error=str(exc))
        return JSONResponse(
            {"status": "not_ready", "reason": f"database unreachable: {exc}"},
            status_code=503,
        )

    try:
        await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=_READYZ_QUERY_TIMEOUT_SECONDS)
    except (TimeoutError, asyncpg.PostgresError) as exc:
        log.warning("readyz_query_failed", error=str(exc))
        return JSONResponse(
            {"status": "not_ready", "reason": f"database query failed: {exc}"},
            status_code=503,
        )
    finally:
        await conn.close()

    return JSONResponse({"status": "ready"})
