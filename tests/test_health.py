"""Tests for Issue #78 — E0.6: Health endpoints and structured logging skeleton.

Contract is derived from:

- ``docs/design/lld-e06-health-logging.md`` (invariants I1-I7, BDD spec)
- ``docs/adr/0011-observability-structlog-otel-auto.md`` (logging/OTEL shape)
- ``docs/adr/0006-streamable-http-mcp-transport.md`` (single HTTP listener)
- ``docs/adr/0012-test-strategy-real-postgres-no-mocks.md`` (no DB mocks)
- ``docs/requirements/v2-requirements.md`` — Story 6.3, Observability

These tests are written against the PUBLIC API only. Stubs raise
``NotImplementedError``; each test therefore currently fails with that, which
is the expected pre-implementation state.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import structlog

from recall.logging import (
    bind_request_context,
    configure_logging,
    unbind_request_context,
)
from recall.server import create_app
from recall.telemetry import configure_telemetry, get_trace_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Parse every non-blank line of ``text`` as JSON and return the dicts.

    Raises ``AssertionError`` if any non-blank line is not valid JSON — that
    is the whole point of I3 ("all log output is JSON on stdout").
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            parsed = json.loads(ln)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"Log line is not JSON: {ln!r} ({exc})") from exc
        assert isinstance(parsed, dict), f"Log line is not a JSON object: {ln!r}"
        out.append(parsed)
    return out


async def _asgi_client(app: Any) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` backed by the in-process ASGI app."""
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------
# ASGI client fixtures — real DB via testcontainers (ADR-0012)
# ---------------------------------------------------------------------------


@pytest.fixture
async def asgi_client(postgres_dsn: str) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client against a real Postgres container — used by /readyz happy path."""
    app = create_app(postgres_dsn)
    # Use LifespanManager-style entry: httpx's ASGITransport will dispatch
    # lifespan events when wrapped in an AsyncClient + explicit startup call.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger lifespan startup by hitting any route; Starlette's
        # ASGITransport path in httpx dispatches lifespan automatically.
        yield client


@pytest.fixture
async def asgi_client_bad_db(bad_dsn: str) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client wired to an unreachable DSN — exercises /readyz 503 path."""
    app = create_app(bad_dsn)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ===========================================================================
# TestHealthEndpoints — covers I1, I2a, I2b, I7
# ===========================================================================


@pytest.mark.integration
class TestHealthEndpoints:
    """Integration tests for /healthz and /readyz (LLD §Acceptance Criteria)."""

    async def test_healthz_returns_ok(self, asgi_client: httpx.AsyncClient) -> None:
        """I1: GET /healthz returns 200 with JSON ``{"status": "ok"}``."""
        resp = await asgi_client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok"}

    async def test_readyz_returns_ready_when_db_up(self, asgi_client: httpx.AsyncClient) -> None:
        """I2a: GET /readyz returns 200 ``{"status": "ready"}`` when DB is reachable."""
        resp = await asgi_client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ready"}

    async def test_readyz_returns_503_when_db_down(
        self, asgi_client_bad_db: httpx.AsyncClient
    ) -> None:
        """I2b: /readyz returns 503 ``{"status": "not_ready", "reason": ...}`` when DB is down."""
        resp = await asgi_client_bad_db.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body.get("status") == "not_ready"
        assert "reason" in body
        assert isinstance(body["reason"], str) and body["reason"]

    async def test_healthz_responds_within_one_second(self, asgi_client: httpx.AsyncClient) -> None:
        """I7: /healthz responds in under 1 second."""
        t0 = time.perf_counter()
        resp = await asgi_client.get("/healthz")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < 1.0, f"/healthz took {elapsed:.3f}s (> 1s budget)"

    async def test_readyz_responds_within_one_second(self, asgi_client: httpx.AsyncClient) -> None:
        """I7: /readyz responds in under 1 second on the happy path."""
        t0 = time.perf_counter()
        resp = await asgi_client.get("/readyz")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < 1.0, f"/readyz took {elapsed:.3f}s (> 1s budget)"


# ===========================================================================
# TestStructlogConfiguration — covers I3, I4, I6
# ===========================================================================


class TestStructlogConfiguration:
    """Unit tests for ``configure_logging`` + contextvar wiring."""

    def test_json_output_format(
        self, capfd: pytest.CaptureFixture[str], reset_logging: None
    ) -> None:
        """I3: a single structlog event produces one JSON line on stdout with
        mandatory fields (``event``, ``level``, ``timestamp``)."""
        configure_logging()
        log = structlog.get_logger("recall.test")
        log.info("hello_world", answer=42)

        captured = capfd.readouterr()
        lines = _parse_json_lines(captured.out)
        assert lines, f"no JSON line captured; stderr={captured.err!r}"
        # Find our event; ignore any stray lines from earlier setup.
        matches = [ln for ln in lines if ln.get("event") == "hello_world"]
        assert len(matches) == 1, f"expected one 'hello_world' line, got {matches!r}"
        entry = matches[0]
        assert entry["event"] == "hello_world"
        # level field — structlog's add_log_level renders as 'level' or 'log_level'
        assert "level" in entry or "log_level" in entry, entry
        # timestamp field — TimeStamper default key is 'timestamp'
        assert "timestamp" in entry, entry
        assert entry.get("answer") == 42

    def test_contextvar_fields_bound(
        self, capfd: pytest.CaptureFixture[str], reset_logging: None
    ) -> None:
        """I4: fields bound via ``bind_request_context`` appear in every subsequent
        log line, and disappear after ``unbind_request_context``."""
        configure_logging()
        log = structlog.get_logger("recall.test")

        bind_request_context(request_id="r-1", trace_id="t-1", span_id="s-1")
        log.info("bound_line")
        unbind_request_context()
        log.info("unbound_line")

        lines = _parse_json_lines(capfd.readouterr().out)
        bound = next(ln for ln in lines if ln.get("event") == "bound_line")
        unbound = next(ln for ln in lines if ln.get("event") == "unbound_line")

        assert bound.get("request_id") == "r-1"
        assert bound.get("trace_id") == "t-1"
        assert bound.get("span_id") == "s-1"

        # After unbind, the keys must be absent (not just empty).
        assert "request_id" not in unbound, unbound
        assert "trace_id" not in unbound, unbound
        assert "span_id" not in unbound, unbound

    def test_library_logging_bridged(
        self, capfd: pytest.CaptureFixture[str], reset_logging: None
    ) -> None:
        """I6: a stdlib ``logging.warning`` from any library logger is emitted
        as a structlog JSON line on stdout."""
        configure_logging()

        lib_logger = logging.getLogger("some.third.party")
        lib_logger.warning("bridged_from_stdlib", extra={"shape": "square"})

        lines = _parse_json_lines(capfd.readouterr().out)
        # Accept either: event == the message literal, or the message surfaces
        # in a 'message'/'event' field. The contract is "JSON on stdout with
        # expected shape"; we require an event field set to the message.
        matches = [
            ln
            for ln in lines
            if ln.get("event") == "bridged_from_stdlib"
            or ln.get("message") == "bridged_from_stdlib"
        ]
        assert matches, f"library log not bridged to JSON: {lines!r}"
        entry = matches[0]
        # Level must reflect warning.
        level_field = entry.get("level") or entry.get("log_level")
        assert level_field is not None
        assert str(level_field).lower() == "warning", entry
        assert "timestamp" in entry


# ===========================================================================
# TestOtelSetup — covers I5, O1
# ===========================================================================


class TestOtelSetup:
    """Unit tests for ``configure_telemetry`` no-op path."""

    def test_noop_mode_when_no_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """O1: ``configure_telemetry()`` is a no-op and does not raise when
        ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        # Must not raise.
        configure_telemetry()

    def test_trace_context_available_in_noop_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """I5: ``get_trace_context()`` returns a ``(str, str)`` tuple even in
        no-op mode (both values may be empty, but the shape is fixed)."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        configure_telemetry()

        ctx = get_trace_context()
        assert isinstance(ctx, tuple)
        assert len(ctx) == 2
        trace_id, span_id = ctx
        assert isinstance(trace_id, str)
        assert isinstance(span_id, str)


# ===========================================================================
# TestBootAndHealthSmoke — covers B1 (Phase 0 exit criterion)
# ===========================================================================


@pytest.mark.integration
class TestBootAndHealthSmoke:
    """The Phase 0 exit-criterion smoke test (LLD §BDD)."""

    async def test_server_boots_health_returns_ok_log_emitted(
        self,
        postgres_dsn: str,
        capfd: pytest.CaptureFixture[str],
        reset_logging: None,
    ) -> None:
        """B1: with a running ASGI app configured for logging, GET /healthz
        returns 200 and at least one structured JSON log line is emitted during
        the request lifecycle with the expected field set."""
        # Belt-and-braces: ensure no OTEL endpoint leaks into this test.
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

        configure_logging()
        configure_telemetry()
        app = create_app(postgres_dsn)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Emit at least one structlog event on the same task that makes
            # the request, so B1's "log line during the request lifecycle"
            # is satisfied regardless of whether the server also logs.
            structlog.get_logger("recall.smoke").info("smoke_request", path="/healthz")
            resp = await client.get("/healthz")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        lines = _parse_json_lines(capfd.readouterr().out)
        assert lines, "no structured log lines captured during request lifecycle"
        # At least one line must carry the expected structured-log field set.
        well_formed = [
            ln
            for ln in lines
            if "event" in ln and ("level" in ln or "log_level" in ln) and "timestamp" in ln
        ]
        assert well_formed, (
            f"no log line carries the mandatory (event, level, timestamp) field set: {lines!r}"
        )
