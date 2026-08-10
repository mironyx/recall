"""Unit tests for the Tool Router — dispatch, validation, error formatting,
logging (Issue #91, E1.6).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.6 (anchor ``LLD-e1-tool-router``)
  — dispatch table, per-tool validation order, RecallError -> {error, hint},
  one ``mcp_call`` log event per call
- ``docs/requirements/v2-requirements.md`` — Story 1.1 AC4 (missing required
  fields), Story 1.2 (scope invariant), Story 2.4 (get full record / not found),
  Story 4.3 (structured {error, hint} errors)
- ``docs/adr/0011-observability-structlog-otel-auto.md`` — mcp_call event shape
- Issue #91 acceptance criteria and BDD specs

Design notes:
- The unit under test is ``recall.tool_router.ToolRouter``. The router holds a
  real ``MemoryService`` whose storage is a stand-in that never touches a
  database: ``put`` raises if any validation path leaks into storage, and
  ``get`` returns None so the router's not_found error formatting runs through
  MemoryService's real contract (``get_by_id`` raises NotFoundError on None).
  Delegation itself is exercised through the real store under
  ``@pytest.mark.integration`` — the database is never mocked (ADR-0012).
- Stubs raise ``NotImplementedError``; every test currently fails with that,
  which is the expected pre-implementation state.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from recall.errors import NotFoundError, ValidationError
from recall.logging import configure_logging
from recall.memory_service import MemoryService
from recall.storage_adapter import StorageAdapter
from recall.tool_router import ToolRouter

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Parse every non-blank line of ``text`` as JSON (test_health convention).

    Raises ``AssertionError`` if any non-blank line is not valid JSON.
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


def _mcp_call_events(captured: str) -> list[dict[str, Any]]:
    """All captured log lines whose event is ``mcp_call``."""
    return [ln for ln in _parse_json_lines(captured) if ln.get("event") == "mcp_call"]


def _assert_single_mcp_call(captured: str, expected: dict[str, Any]) -> None:
    """Assert exactly one mcp_call event matching ``expected`` (ADR-0011 S6.3).

    ``expected`` carries the tool, user_id, project_id and result_status
    values; latency_ms is only checked for numeric type. Shared by the
    validation-error and not-found logging tests, which differ only in the
    expected values.
    """
    events = _mcp_call_events(captured)
    assert len(events) == 1, events
    event = events[0]
    assert event["tool"] == expected["tool"]
    assert event["user_id"] == expected["user_id"]
    assert event["project_id"] == expected["project_id"]
    assert isinstance(event["latency_ms"], (int, float))
    assert event["result_status"] == expected["result_status"]


def _save_params(**overrides: Any) -> dict[str, Any]:
    """Valid memory_save params for a project-scoped call (Story 1.1 AC1)."""
    params: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-42",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    params.update(overrides)
    return params


def _service_save_args(**overrides: Any) -> dict[str, Any]:
    """Valid MemoryService.save() kwargs for a project-scoped memory.

    Justification (CodeScene: code duplication): the e2e sibling
    ``test_e2e_phase1._save_params`` carries no ``user_id`` — there the
    identity comes from the bearer token, not the params; merging the two
    builders would couple the test files for five lines.
    """
    args: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-42",
        "user_id": "alice",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    args.update(overrides)
    return args


class _StorageDouble(StorageAdapter):
    """Storage stand-in for router unit tests — never touches a database.

    Subclasses ``StorageAdapter`` so ``MemoryService`` accepts it under
    ``mypy --strict``; ``__init__`` drops the required ``store`` argument
    and does not call ``super().__init__`` — the stand-in never holds a
    real store, and ``put``/``get`` are fully overridden.

    ``put`` raises ``AssertionError``: validation-failure paths must never
    reach storage, so any accidental delegation fails the test loudly.
    ``get`` returns None so the router's not_found error formatting can be
    exercised through the real MemoryService contract (``get_by_id`` raises
    NotFoundError when the item is None) without a database.
    """

    def __init__(self, _store: AsyncPostgresStore | None = None) -> None:
        """Stand-in: the store argument is accepted for signature compatibility only."""

    async def put(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("storage.put must not be reached in a unit test")

    async def get(self, *args: Any, **kwargs: Any) -> None:
        return None


class _BoomStorage(StorageAdapter):
    """Storage stand-in whose put() raises a non-RecallError.

    Subclasses ``StorageAdapter`` for the same reason as ``_StorageDouble``:
    ``MemoryService`` requires it under ``mypy --strict``.

    Simulates an unexpected failure inside the service boundary (e.g. an
    embedding provider error) so the router's RecallError-only catch boundary
    can be exercised without a database.
    """

    def __init__(self, _store: AsyncPostgresStore | None = None) -> None:
        """Stand-in: the store argument is accepted for signature compatibility only."""

    async def put(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("embedding provider unavailable")

    async def get(self, *args: Any, **kwargs: Any) -> None:
        return None


def _unit_router() -> ToolRouter:
    """ToolRouter over a real MemoryService with the storage stand-in.

    Validation, error formatting, and logging paths never need storage; the
    stand-in guards that they do not reach it. Delegation is covered by the
    integration-marked tests with the real store fixture.
    """
    service = MemoryService(_StorageDouble())
    return ToolRouter(service)


@pytest_asyncio.fixture
async def service(store: AsyncPostgresStore) -> MemoryService:
    """MemoryService over the session-scoped real-store fixture (conftest)."""
    return MemoryService(StorageAdapter(store))


# ---------------------------------------------------------------------------
# memory_save validation (Issue #91 AC1; Story 1.1 AC4, Story 1.2)
# ---------------------------------------------------------------------------


class TestMemorySaveValidation:
    """Router-level validation for memory_save — the API boundary (LLD §E1.6)."""

    @pytest.mark.parametrize("missing_field", ["scope", "kind", "title", "content"])
    async def test_missing_required_field_rejected(self, missing_field: str) -> None:
        """Given memory_save missing one of scope/kind/title/content, when
        handled, then {error: 'validation_error'} names the missing field
        (Story 1.1 AC4; Issue #91 AC1)."""
        params = _save_params()
        del params[missing_field]

        result = await _unit_router().handle_tool_call("memory_save", params, "alice")

        expected_hint = ValidationError(f"Missing required field: {missing_field}").hint
        assert result == {"error": "validation_error", "hint": expected_hint}

    async def test_empty_required_field_rejected(self) -> None:
        """Given a required field present but empty (''), the call is rejected
        exactly like a missing one — the boundary treats both as absent."""
        params = _save_params(kind="")

        result = await _unit_router().handle_tool_call("memory_save", params, "alice")

        assert result == {
            "error": "validation_error",
            "hint": ValidationError("Missing required field: kind").hint,
        }

    @pytest.mark.parametrize(
        ("project_id", "expected_hint"),
        [
            pytest.param("", "project_id must not be empty", id="empty"),
            pytest.param(
                "bad id!",
                "project_id 'bad id!' is invalid. Must match ^[a-zA-Z0-9_-]{1,128}$",
                id="special-chars",
            ),
            pytest.param(
                "global",
                "'global' is a reserved name and cannot be used as a project_id",
                id="reserved-global",
            ),
            pytest.param(
                "GLOBAL",
                "'GLOBAL' is a reserved name and cannot be used as a project_id",
                id="reserved-global-case-insensitive",
            ),
            pytest.param(
                "_",
                "'_' is a reserved name and cannot be used as a project_id",
                id="reserved-sentinel",
            ),
            pytest.param(
                "a" * 129,
                f"project_id '{'a' * 129}' is invalid. Must match ^[a-zA-Z0-9_-]{{1,128}}$",
                id="too-long",
            ),
        ],
    )
    async def test_invalid_project_id_format_rejected(
        self, project_id: str, expected_hint: str
    ) -> None:
        """Given a project_id violating ^[a-zA-Z0-9_-]{1,128}$ or a reserved
        name, memory_save with scope=project returns {error: 'validation_error'}
        with the validator's hint (ADR-0014; LLD invariant I9)."""
        result = await _unit_router().handle_tool_call(
            "memory_save", _save_params(project_id=project_id), "alice"
        )

        assert result == {"error": "validation_error", "hint": expected_hint}

    async def test_missing_project_id_rejected(self) -> None:
        """Given scope=project without a project_id at all, the call is
        rejected — project scope requires a project ID (Story 1.2 AC2)."""
        params = _save_params()
        del params["project_id"]

        result = await _unit_router().handle_tool_call("memory_save", params, "alice")

        assert result["error"] == "validation_error"
        assert "project_id" in result["hint"]

    async def test_global_scope_with_project_id_rejected(self) -> None:
        """Given scope=global with a project_id, the call is rejected with an
        error indicating global scope must not carry a project ID (Story 1.2
        AC4; LLD invariant I2)."""
        result = await _unit_router().handle_tool_call(
            "memory_save", _save_params(scope="global", project_id="proj-42"), "alice"
        )

        assert result["error"] == "validation_error"
        assert "global" in result["hint"]
        assert "project_id" in result["hint"]

    async def test_unknown_scope_rejected(self) -> None:
        """Given a scope other than 'project' or 'global', the call is rejected
        with an error indicating the invalid scope (Story 1.2 AC5)."""
        result = await _unit_router().handle_tool_call(
            "memory_save", _save_params(scope="team"), "alice"
        )

        assert result["error"] == "validation_error"
        assert "scope" in result["hint"]


# ---------------------------------------------------------------------------
# memory_get validation (Issue #91 AC2; Story 2.4)
# ---------------------------------------------------------------------------


class TestMemoryGetValidation:
    """Router-level validation for memory_get — scope, project_id and id are
    all required; the namespace is explicit (ADR-0015)."""

    @pytest.mark.parametrize("missing_field", ["scope", "project_id", "id"])
    async def test_missing_required_field_rejected(self, missing_field: str) -> None:
        """Given memory_get without one of scope/project_id/id, when handled,
        then {error: 'validation_error'} is returned (LLD _handle_memory_get)."""
        params = {"scope": "project", "project_id": "proj-42", "id": str(uuid.uuid4())}
        del params[missing_field]

        result = await _unit_router().handle_tool_call("memory_get", params, "alice")

        assert result == {
            "error": "validation_error",
            "hint": "Missing required field: scope, project_id, id",
        }

    async def test_empty_id_rejected(self) -> None:
        """Given an empty-string id, the call is rejected like a missing one."""
        params = {"scope": "project", "project_id": "proj-42", "id": ""}

        result = await _unit_router().handle_tool_call("memory_get", params, "alice")

        assert result["error"] == "validation_error"
        assert result["hint"] == "Missing required field: scope, project_id, id"

    async def test_not_found_returns_structured_error(self) -> None:
        """Given a memory_get for an id that does not exist, then
        {error: 'not_found', hint} is returned with the memory id in the hint
        — asserted via the error/hint attributes, not str() (Story 2.4 AC2;
        Issue #91 AC2)."""
        memory_id = str(uuid.uuid4())

        result = await _unit_router().handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "proj-42", "id": memory_id},
            "alice",
        )

        assert result == {"error": "not_found", "hint": NotFoundError(memory_id).hint}
        assert memory_id in result["hint"]


# ---------------------------------------------------------------------------
# Dispatch and error handling (Issue #91 AC1/AC4; LLD _dispatch)
# ---------------------------------------------------------------------------


class TestToolRouterDispatch:
    """Dispatch-table routing and the RecallError-only catch boundary."""

    async def test_unknown_tool_rejected(self) -> None:
        """Given a tool name that is not registered, when handled, then
        {error: 'validation_error'} is returned naming the unknown tool
        (LLD _dispatch else-branch)."""
        result = await _unit_router().handle_tool_call("memory_delete", _save_params(), "alice")

        assert result["error"] == "validation_error"
        assert "Unknown tool" in result["hint"]

    async def test_unexpected_service_error_propagates(self) -> None:
        """Given the service raises a non-RecallError (e.g. embedding provider
        failure), handle_tool_call does not swallow it — only RecallError is
        caught (LLD handle_tool_call try/except; Story 4.3 AC4 leaves server
        errors to the transport layer)."""
        service = MemoryService(_BoomStorage())
        router = ToolRouter(service)

        with pytest.raises(RuntimeError, match="embedding provider unavailable"):
            await router.handle_tool_call("memory_save", _save_params(), "alice")


# ---------------------------------------------------------------------------
# Structured mcp_call logging (Issue #91 AC3; ADR-0011 S6.3)
# ---------------------------------------------------------------------------


class TestToolRouterLogging:
    """Every handle_tool_call emits exactly one mcp_call log event with
    tool, user_id, project_id, latency_ms and result_status (LLD)."""

    async def test_validation_error_emits_single_mcp_call_event(
        self, capfd: pytest.CaptureFixture[str], reset_logging: None
    ) -> None:
        """Given a validation-failing memory_save, exactly one mcp_call event
        is emitted with result_status='validation_error'."""
        configure_logging()
        await _unit_router().handle_tool_call(
            "memory_save", {"kind": "decision", "title": "t", "content": "c"}, "alice"
        )

        _assert_single_mcp_call(
            capfd.readouterr().out,
            {
                "tool": "memory_save",
                "user_id": "alice",
                "project_id": "",
                "result_status": "validation_error",
            },
        )

    async def test_not_found_emits_single_mcp_call_event(
        self, capfd: pytest.CaptureFixture[str], reset_logging: None
    ) -> None:
        """Given a memory_get miss, exactly one mcp_call event is emitted with
        result_status='not_found' and the requested project_id."""
        configure_logging()
        await _unit_router().handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "proj-42", "id": str(uuid.uuid4())},
            "alice",
        )

        _assert_single_mcp_call(
            capfd.readouterr().out,
            {
                "tool": "memory_get",
                "user_id": "alice",
                "project_id": "proj-42",
                "result_status": "not_found",
            },
        )


# ---------------------------------------------------------------------------
# Delegation — real Postgres via the session-scoped store fixture (ADR-0012)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMemorySaveDelegation:
    """Router -> MemoryService delegation for memory_save against the real
    store — the database is never mocked (CLAUDE.md)."""

    async def test_save_delegates_to_service_and_returns_id(self, service: MemoryService) -> None:
        """Given valid params, when handle_tool_call('memory_save') is called,
        then {'id': <uuid4>} is returned and the memory is persisted with the
        resolved user_id and pass-through tags/metadata (Issue #91 AC1)."""
        router = ToolRouter(service)

        result = await router.handle_tool_call(
            "memory_save",
            _save_params(tags=["architecture"], metadata={"source": "adr-0001"}),
            "alice",
        )

        assert set(result) == {"id"}
        memory_id = result["id"]
        assert uuid.UUID(memory_id).version == 4
        record = await service.get_by_id("project", "proj-42", memory_id)
        assert record["user_id"] == "alice"
        assert record["tags"] == ["architecture"]
        assert record["metadata"] == {"source": "adr-0001"}

    async def test_global_save_delegates_under_sentinel(self, service: MemoryService) -> None:
        """Given scope=global without project_id, the router passes the '_'
        sentinel down so the memory lands under ('global', '_')
        (LLD _handle_memory_save; Story 5.4 AC2)."""
        router = ToolRouter(service)

        result = await router.handle_tool_call(
            "memory_save",
            {
                "scope": "global",
                "kind": "preference",
                "title": "Terse PRs",
                "content": "Prefer terse PR descriptions.",
            },
            "alice",
        )

        memory_id = result["id"]
        record = await service.get_by_id("global", "_", memory_id)
        assert record["scope"] == "global"
        assert record["project_id"] == "_"


@pytest.mark.integration
class TestMemoryGetDelegation:
    """Router -> MemoryService delegation for memory_get against the real store."""

    async def test_get_delegates_and_returns_full_record(self, service: MemoryService) -> None:
        """Given a saved memory, when handle_tool_call('memory_get') is called
        with its scope, project_id and id, then the full record is returned
        (Issue #91 AC2; Story 2.4 AC1; LLD invariant I6)."""
        memory_id = await service.save(**_service_save_args())
        router = ToolRouter(service)

        record = await router.handle_tool_call(
            "memory_get",
            {"scope": "project", "project_id": "proj-42", "id": memory_id},
            "alice",
        )

        assert record["id"] == memory_id
        assert record["scope"] == "project"
        assert record["project_id"] == "proj-42"
        assert record["user_id"] == "alice"
        assert record["kind"] == "decision"
        assert record["title"] == "Use event sourcing"
        assert record["content"] == "The billing service uses event sourcing."
        assert record["created_at"] == record["updated_at"]
