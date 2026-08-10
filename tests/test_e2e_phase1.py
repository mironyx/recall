"""End-to-end integration tests for Phase 1 — memory_save + memory_get over
real MCP transport (Issue #91, E1.6).

Contract sources:
- Issue #91 BDD specs — ``TestMemorySaveEndToEnd`` / ``TestMemoryGetEndToEnd``
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.6 (anchors
  ``LLD-e1-tool-router``, ``LLD-e1-mcp-tool-declarations``) and invariants
  I1-I7 — the Phase 1 exit criterion
- ``docs/requirements/v2-requirements.md`` — Stories 1.1, 1.2 (save + scope
  invariant), 2.4 (get full record / not found), 4.1 (Streamable HTTP), 4.3
  (structured errors), 5.1, 5.6 (bearer token auth)
- ``docs/adr/0011-observability-structlog-otel-auto.md`` — mcp_call event shape

Design notes:
- The full request path is exercised: bearer auth -> MCP Streamable HTTP
  transport -> tool router -> memory service -> real Postgres via
  testcontainers (ADR-0012). The store is never mocked (CLAUDE.md).
- ``httpx.ASGITransport`` does not run the app lifespan, and the MCP session
  manager lives in it — so the lifespan and the MCP client are entered
  together inside each test via ``_e2e_client``. Both wrap anyio task groups,
  which cannot cross pytest-asyncio's fixture setup/teardown task boundary
  ("Attempted to exit cancel scope in a different task"), and function-scoped
  async fixtures run on a different event loop than the module-scoped tests,
  stalling the transport rendezvous — so no fixture opens a client.
- The session-scoped ``_migrated_db_sess`` conftest fixture ensures the schema
  exists once per session; per-test TRUNCATE isolation reuses conftest's
  ``_truncate_all``.
- Auth failures are returned as structured tool results (content carrying
  {error: 'unauthenticated'}), NOT JSON-RPC errors — assertions read the
  returned ``CallToolResult`` payload.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from starlette.applications import Starlette

from recall.logging import configure_logging
from recall.server import create_app
from tests.conftest import _truncate_all

AUTH_HEADERS = {"Authorization": "Bearer test-token"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Parse every non-blank line of ``text`` as JSON (test_health convention)."""
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


def _unpack_result(result: CallToolResult) -> dict[str, Any]:
    """Extract the JSON payload dict from a CallToolResult.

    The server returns tool results either as ``structured_content`` (dict)
    or as JSON text content; auth failures are formatted as structured tool
    results, NOT JSON-RPC errors (Issue #91), so both shapes must be readable.
    """
    if result.structured_content:
        return dict(result.structured_content)
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                payload = json.loads(block.text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    raise AssertionError(f"CallToolResult carries no JSON payload: {result!r}")


def _save_params(**overrides: Any) -> dict[str, Any]:
    """Valid memory_save params for a project-scoped call (Story 1.1 AC1)."""
    params: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-e2e",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    params.update(overrides)
    return params


class _McpClient:
    """Minimal MCP client wrapper: ``call_tool`` -> CallToolResult."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def call_tool(self, name: str, params: dict[str, Any]) -> CallToolResult:
        return await self._session.call_tool(name, params)


@asynccontextmanager
async def _e2e_client(app: Starlette, headers: dict[str, str]) -> AsyncIterator[_McpClient]:
    """Enter the app lifespan and open an MCP Streamable HTTP client.

    ``httpx.ASGITransport`` does not run the app lifespan, so it is entered
    here, in the calling test's task: the lifespan's MCP dispatcher task
    group and the MCP client wrap anyio task groups, which must be entered
    and exited by the same task (see the ``app`` fixture docstring).
    ``headers`` ride on every request (tool calls). The 2026-07-28 protocol
    is stateless (design decision, PR #117) — no initialize handshake, no
    MCP-Session-Id; each POST is self-contained, so the first call works
    directly.
    """
    async with app.router.lifespan_context(app):
        # httpx2 is the httpx 2.x distribution the mcp SDK 2.0.0 transports
        # are typed against (mcp pulls it as a dependency).
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        )
        try:
            async with (
                streamable_http_client("http://testserver/mcp", http_client=http) as (
                    read,
                    write,
                ),
                ClientSession(read, write) as session,
            ):
                yield _McpClient(session)
        finally:
            await http.aclose()


async def _save_memory(client: _McpClient) -> str:
    """Save a project memory via the MCP client and return its id (BDD)."""
    result = await client.call_tool("memory_save", _save_params())
    payload = _unpack_result(result)
    assert set(payload) == {"id"}
    memory_id = payload["id"]
    assert isinstance(memory_id, str)
    return memory_id


# ---------------------------------------------------------------------------
# Fixture stack — app, DB isolation, logs (Issue #91 BDD)
# ---------------------------------------------------------------------------


@pytest.fixture
def app(
    pg_conn_string: str,
    _migrated_db_sess: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Starlette]:
    """Starlette app with the MCP endpoint mounted (lifespan NOT entered).

    Function-scoped because the store that ``create_app`` builds is a
    single-use async context manager (``AsyncPostgresStore.from_conn_string``
    drops its internals on first entry) — each test needs a fresh app to
    enter its own lifespan. ``RECALL_AUTH_FILE`` points at a temp auth file
    mapping the test token to ``alice`` (Story 5.6); embedding dim env vars
    are cleared so the server defaults match the schema default 1536 that
    ``ensure_schema`` used (schema.py / conftest). The lifespan is
    deliberately not entered here: it runs the MCP session manager, an anyio
    task group that must be entered and exited by the same task, but
    pytest-asyncio tears async fixtures down in a different task than it
    sets them up (and function-scoped fixtures on a different event loop
    than the module-scoped tests). Each test instead enters lifespan +
    client together inside ``_e2e_client``.
    """
    auth_file = tmp_path_factory.mktemp("e2e-auth") / "auth.json"
    auth_file.write_text(json.dumps({"test-token": {"user_id": "alice"}}))

    saved_env = {
        var: os.environ.get(var)
        for var in ("RECALL_AUTH_FILE", "RECALL_EMBEDDING_DIMS", "RECALL_EMBEDDINGS_DIM")
    }
    try:
        os.environ["RECALL_AUTH_FILE"] = str(auth_file)
        for var in ("RECALL_EMBEDDING_DIMS", "RECALL_EMBEDDINGS_DIM"):
            os.environ.pop(var, None)

        yield create_app(pg_conn_string)
    finally:
        for var, value in saved_env.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(pg_conn_string: str) -> AsyncIterator[None]:
    """Per-test isolation — TRUNCATE data tables before each e2e test (E0.5)."""
    await _truncate_all(pg_conn_string)
    yield


@pytest.fixture
def project_id() -> str:
    """A well-formed project identifier for e2e tests."""
    return "proj-e2e"


# ===========================================================================
# BDD — TestMemorySaveEndToEnd (Issue #91)
# ===========================================================================


@pytest.mark.integration
class TestMemorySaveEndToEnd:
    """Phase 1 exit criterion — save and retrieve over real MCP transport."""

    async def test_save_project_memory_round_trip(self, app: Starlette, project_id: str) -> None:
        """Given a valid bearer token and a well-formed project_id,
        when memory_save is called with scope=project,
        then an id is returned and memory_get retrieves the full record."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            save_result = await client.call_tool("memory_save", _save_params())
            payload = _unpack_result(save_result)
            assert set(payload) == {"id"}
            memory_id = payload["id"]
            assert uuid.UUID(memory_id).version == 4

            get_result = await client.call_tool(
                "memory_get",
                {"scope": "project", "project_id": project_id, "id": memory_id},
            )
            record = _unpack_result(get_result)

            assert record["id"] == memory_id
            assert record["scope"] == "project"
            assert record["project_id"] == project_id
            assert record["user_id"] == "alice"
            assert record["kind"] == "decision"
            assert record["title"] == "Use event sourcing"
            assert record["content"] == "The billing service uses event sourcing."
            assert record["tags"] == []
            assert record["metadata"] == {}
            assert "created_at" in record
            assert "updated_at" in record
            assert record["created_at"] == record["updated_at"]

    async def test_save_global_memory(self, app: Starlette) -> None:
        """Given scope=global and no project_id,
        when memory_save is called,
        then the memory is stored under namespace ('global', '_')."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            save_result = await client.call_tool(
                "memory_save",
                {
                    "scope": "global",
                    "kind": "preference",
                    "title": "Terse PRs",
                    "content": "Prefer terse PR descriptions.",
                },
            )
            memory_id = _unpack_result(save_result)["id"]

            get_result = await client.call_tool(
                "memory_get",
                {"scope": "global", "project_id": "_", "id": memory_id},
            )
            record = _unpack_result(get_result)
            assert record["scope"] == "global"
            assert record["project_id"] == "_"

    async def test_save_fails_without_auth(self, app: Starlette) -> None:
        """Given no bearer token,
        when memory_save is called,
        then {error: 'unauthenticated'} is returned."""
        async with _e2e_client(app, {}) as client:
            result = await client.call_tool("memory_save", _save_params())
            payload = _unpack_result(result)

            assert payload.get("error") == "unauthenticated"
            assert payload.get("hint")

    async def test_save_fails_with_invalid_project_id_format(self, app: Starlette) -> None:
        """Given invalid project_id,
        when memory_save is called with scope=project,
        then {error: 'validation_error'} is returned."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            for bad_id in ("bad id!", "global", "_"):
                result = await client.call_tool("memory_save", _save_params(project_id=bad_id))
                payload = _unpack_result(result)
                assert payload.get("error") == "validation_error", bad_id
                assert payload.get("hint")

    async def test_save_validates_scope_invariant(self, app: Starlette) -> None:
        """Given scope=global with a project_id,
        when memory_save is called,
        then {error: 'validation_error'} is returned."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            result = await client.call_tool(
                "memory_save", _save_params(scope="global", project_id="proj-e2e")
            )
            payload = _unpack_result(result)

            assert payload.get("error") == "validation_error"
            assert payload.get("hint")

    async def test_structured_log_emitted(
        self,
        app: Starlette,
        project_id: str,
        capfd: pytest.CaptureFixture[str],
        reset_logging: None,
    ) -> None:
        """Given a successful memory_save,
        then exactly one mcp_call log event is emitted with
        request_id, user_id, project_id, tool='memory_save',
        latency_ms, result_status='ok'."""
        # test_health convention: configure_logging() must run in the test
        # body — at fixture setup the root handler binds a pre-capture
        # sys.stdout and the events miss capfd.
        configure_logging()
        async with _e2e_client(app, AUTH_HEADERS) as client:
            result = await client.call_tool("memory_save", _save_params())
            assert _unpack_result(result)["id"]  # the save succeeded

        # The router binds tool/user_id/project_id/latency_ms/result_status
        # (LLD); transport-bound fields (request_id/trace_id/span_id) come from
        # the middleware contextvar and are not asserted here.
        events = [
            ln for ln in _parse_json_lines(capfd.readouterr().out) if ln.get("event") == "mcp_call"
        ]
        assert len(events) == 1, events
        event = events[0]
        assert event["tool"] == "memory_save"
        assert event["user_id"] == "alice"
        assert event["project_id"] == project_id
        assert isinstance(event["latency_ms"], (int, float))
        assert event["result_status"] == "ok"


# ===========================================================================
# BDD — TestMemoryGetEndToEnd (Issue #91)
# ===========================================================================


@pytest.mark.integration
class TestMemoryGetEndToEnd:
    """Phase 1 exit criterion — get the full record of a saved memory."""

    async def test_get_returns_full_record(self, app: Starlette, project_id: str) -> None:
        """Given a saved memory,
        when memory_get is called with its scope, project_id and id,
        then the full record is returned with all fields."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            memory_id = await _save_memory(client)
            result = await client.call_tool(
                "memory_get",
                {"scope": "project", "project_id": project_id, "id": memory_id},
            )
            record = _unpack_result(result)

            assert record["id"] == memory_id
            assert record["scope"] == "project"
            assert record["project_id"] == project_id
            assert record["user_id"] == "alice"
            assert record["kind"] == "decision"
            assert record["title"] == "Use event sourcing"
            assert record["content"]
            assert "created_at" in record
            assert "updated_at" in record

    async def test_get_not_found(self, app: Starlette) -> None:
        """Given a non-existent id in a known namespace,
        when memory_get is called,
        then {error: 'not_found'} is returned."""
        async with _e2e_client(app, AUTH_HEADERS) as client:
            result = await client.call_tool(
                "memory_get",
                {"scope": "project", "project_id": "proj-e2e", "id": str(uuid.uuid4())},
            )
            payload = _unpack_result(result)

            assert payload.get("error") == "not_found"
            assert payload.get("hint")
