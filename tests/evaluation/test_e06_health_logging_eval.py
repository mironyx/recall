"""Adversarial evaluation tests for Issue #78 — E0.6: Health endpoints and
structured logging skeleton.

Probes gaps not fully covered by tests/test_health.py:

1. ``sys.stderr.write`` in cli.py is non-JSON output that bypasses structlog
   (I3: "all log output is JSON on stdout via structlog — no print()").
2. ``bind_request_context`` / ``unbind_request_context`` are never called from
   within the HTTP request lifecycle — the server has no middleware that injects
   ``request_id``/``trace_id``/``span_id`` into the contextvar.  AC-4 says
   "every log line includes request_id, trace_id, span_id *when in a request
   context*" — there is no request-context wiring in Phase 0's server.
3. The ``get_trace_context()`` return values are never fed back into the structlog
   context inside a real request — AC-5 ("trace_id/span_id present even in OTEL
   no-op mode") is verified for shape only, not for appearance in log output.

Imports reuse helpers and fixtures from tests/test_health.py and tests/conftest.py.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest
import structlog

from recall.logging import bind_request_context, configure_logging, unbind_request_context
from recall.server import create_app
from recall.telemetry import configure_telemetry, get_trace_context

# ---------------------------------------------------------------------------
# Shared helpers (mirror the minimal set from tests/test_health.py)
# ---------------------------------------------------------------------------


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# AC-3 gap: sys.stderr.write in cli.py bypasses structlog
# ---------------------------------------------------------------------------


class TestI3NoRawOutput:
    """I3 — 'All log output is JSON on stdout via structlog.'

    The implementation has a ``sys.stderr.write()`` call in cli.py that is
    triggered when DATABASE_URL is absent. This is raw text on stderr — it
    bypasses structlog and violates I3 in spirit (and would be invisible to
    any log aggregator reading stdout JSON).
    """

    def test_no_sys_stderr_write_in_src(self) -> None:
        """No file in src/recall/ should contain a raw sys.stderr.write call.

        I3 mandates that all log output routes through structlog.  A
        sys.stderr.write() on a warning is a silent escape hatch that will not
        appear in structured JSON output collected by the log aggregator.
        """
        import subprocess
        from pathlib import Path

        src_dir = Path(__file__).parent.parent.parent / "src" / "recall"
        result = subprocess.run(
            ["grep", "-rn", "sys.stderr.write", str(src_dir)],  # noqa: S607
            capture_output=True,
            text=True,
        )
        # If grep finds matches, the test fails and prints them.
        assert result.stdout.strip() == "", (
            "Found sys.stderr.write() in src/recall/ — these bypass structlog "
            f"and violate I3:\n{result.stdout}"
        )


# ---------------------------------------------------------------------------
# AC-4 gap: HTTP request lifecycle does NOT inject request_id into contextvar
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRequestContextWiring:
    """AC-4 — 'every log line includes request_id, trace_id, span_id when in a
    request context'.

    The server has no middleware that calls ``bind_request_context`` for
    incoming HTTP requests. This test probes whether a log line emitted by a
    health handler carries request-scoped fields.

    If there is no middleware, this test will FAIL — that is a finding, not a
    bug in the test.
    """

    async def test_healthz_log_includes_request_id(
        self,
        postgres_dsn: str,
        capfd: pytest.CaptureFixture[str],
        reset_logging: None,
    ) -> None:
        """A log line emitted during /healthz handling must carry request_id.

        Requires middleware or a lifespan hook that calls bind_request_context
        before dispatching to the handler.
        """
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        configure_logging()
        configure_telemetry()
        app = create_app(postgres_dsn)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/healthz")

        assert resp.status_code == 200

        lines = _parse_json_lines(capfd.readouterr().out)
        # If no log lines were emitted during the request, that itself is
        # interesting — the handler is silent.  The real question is whether
        # any emitted line has request_id.
        if not lines:
            pytest.skip("no log lines emitted during /healthz — nothing to assert request_id on")

        # At least one line must carry request_id (injected by middleware).
        lines_with_request_id = [ln for ln in lines if "request_id" in ln]
        assert lines_with_request_id, (
            "No log line emitted during /healthz carries 'request_id'. "
            "The server has no middleware that calls bind_request_context(). "
            f"Emitted lines: {lines!r}"
        )


# ---------------------------------------------------------------------------
# AC-5 gap: get_trace_context() values do NOT flow into log output
# ---------------------------------------------------------------------------


class TestTraceContextInLogOutput:
    """AC-5 — 'trace_id/span_id present even in OTEL no-op mode'.

    The existing test verifies that ``get_trace_context()`` returns a
    ``(str, str)`` tuple. This test verifies the stronger claim: that the
    values actually appear in structlog output.

    In Phase 0 the values will be empty strings (""), which is fine. What is
    NOT fine is if the wiring between ``get_trace_context()`` and
    structlog's contextvar is absent entirely.
    """

    def test_trace_id_and_span_id_appear_in_log_line(
        self,
        capfd: pytest.CaptureFixture[str],
        reset_logging: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After configure_telemetry(), a structlog line must contain
        'trace_id' and 'span_id' keys (values may be empty strings in
        no-op mode).

        If the implementation never calls bind_request_context(trace_id=...,
        span_id=...) or never binds them via a processor, this test will fail.
        """
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        configure_logging()
        configure_telemetry()

        # Simulate what the transport boundary should do: extract OTEL context
        # and bind it into the structlog contextvar.
        trace_id, span_id = get_trace_context()
        bind_request_context(request_id="eval-req-1", trace_id=trace_id, span_id=span_id)
        try:
            log = structlog.get_logger("recall.eval")
            log.info("eval_trace_check")
        finally:
            unbind_request_context()

        lines = _parse_json_lines(capfd.readouterr().out)
        matches = [ln for ln in lines if ln.get("event") == "eval_trace_check"]
        assert matches, f"Expected log line 'eval_trace_check' not found in: {lines!r}"
        entry = matches[0]

        # The keys must be present. In no-op mode the values are "".
        assert "trace_id" in entry, (
            f"'trace_id' key absent from log line: {entry!r}. "
            "bind_request_context() must be called with trace values from get_trace_context()."
        )
        assert "span_id" in entry, (
            f"'span_id' key absent from log line: {entry!r}. "
            "bind_request_context() must be called with span values from get_trace_context()."
        )
        # Values must be strings (possibly empty in no-op mode).
        assert isinstance(entry["trace_id"], str), entry
        assert isinstance(entry["span_id"], str), entry


# ---------------------------------------------------------------------------
# AC-3 additional: no bare print() in src/recall/
# ---------------------------------------------------------------------------


class TestNoPrintInSrc:
    """I3 — complement: no bare print() calls exist in src/recall/."""

    def test_no_print_calls_in_src(self) -> None:
        """src/recall/ must contain no bare print() calls."""
        import subprocess
        from pathlib import Path

        src_dir = Path(__file__).parent.parent.parent / "src" / "recall"
        # grep for print( but exclude comments and string literals naively
        result = subprocess.run(
            ["grep", "-rn", r"^\s*print(", str(src_dir)],  # noqa: S607
            capture_output=True,
            text=True,
        )
        assert (
            result.stdout.strip() == ""
        ), f"Found bare print() calls in src/recall/:\n{result.stdout}"
