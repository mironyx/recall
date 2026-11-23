"""Error vocabulary — ErrorCode registry and embedding_failed (REC-12, E3.3a).

Contract sources:
- ``docs/design/v2/lld-e3-update-delete-errors.md`` §3.4 (anchor ``LLD-e3-errors``) —
  the five-code table, invariants 1-5, ``guarded_embed`` and ``EmbeddingError`` shapes
- ``docs/requirements/v2-requirements.md`` — Story 1.3 AC4/AC5 (embedding failure is a
  structured error, nothing stored), Story 4.3 (structured ``{error, hint}`` errors)
- REC-12 acceptance criteria and BDD specs

Design notes:
- Envelope tests go through the real ``ToolRouter`` over a real ``AsyncPostgresStore``
  (ADR-0012); ``unauthenticated`` goes through the MCP transport because auth is
  resolved there, not in the router.
- ``failing_embedding_store`` (conftest) is a real store whose *provider* raises
  ``RuntimeError(FAILING_PROVIDER_DETAIL)`` through ``guarded_embed`` — a provider
  double, not a store mock.
- Stubs raise ``NotImplementedError``; the tests fail until the implementation lands.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import psycopg
import pytest

from recall.embeddings.provider import EmbeddingsProvider, guarded_embed
from recall.embeddings.stub import StubEmbeddingsProvider
from recall.errors import (
    EmbeddingError,
    ErrorCode,
    NotFoundError,
    RecallError,
    UnauthenticatedError,
    ValidationError,
)
from recall.memory_service import MemoryService
from recall.storage_adapter import StorageAdapter
from recall.tool_router import ToolRouter
from tests.conftest import FAILING_PROVIDER_DETAIL, _PerCallClient

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore

_SRC = Path(__file__).resolve().parent.parent / "src" / "recall"
_PROJECT = "proj-errors"
_CODES = ("unauthenticated", "validation_error", "not_found", "embedding_failed", "internal_error")

Logs = list[MutableMapping[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_params(**overrides: Any) -> dict[str, Any]:
    """Valid project-scoped memory_save params."""
    params: dict[str, Any] = {
        "scope": "project",
        "project_id": _PROJECT,
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    params.update(overrides)
    return params


def _locator(memory_id: str) -> dict[str, Any]:
    return {"scope": "project", "project_id": _PROJECT, "id": memory_id}


def _router(store: AsyncPostgresStore) -> ToolRouter:
    """The real router over a real service and adapter on ``store``."""
    return ToolRouter(MemoryService(StorageAdapter(store)))


async def _store_row_count(conn_string: str) -> int:
    """Rows in the store's item table (all namespaces)."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute("SELECT COUNT(*) FROM store")
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def _vector_row_count(conn_string: str, key: str) -> int:
    async with (
        await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute("SELECT COUNT(*) FROM store_vectors WHERE key = %s", (key,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


def _assert_envelope(result: dict[str, Any], code: str) -> None:
    """Invariant 2 — exactly ``{error, hint}``, error is the code, hint non-empty."""
    assert set(result) == {"error", "hint"}, result
    assert result["error"] == code
    assert isinstance(result["hint"], str)
    assert result["hint"].strip()
    # On the wire the code serialises to the bare string (wire shape unchanged).
    assert json.loads(json.dumps(result))["error"] == code


def _assert_no_leak(result: dict[str, Any]) -> None:
    """Invariant 3 — the provider's message and exception type never reach the caller."""
    wire = json.dumps(result)
    assert FAILING_PROVIDER_DETAIL not in wire
    assert "RuntimeError" not in wire
    assert "Traceback" not in wire


class _ListProvider(EmbeddingsProvider):
    """Provider double that records the argument type and returns fixed vectors."""

    def __init__(self) -> None:
        self.received: list[object] = []

    @property
    def dim(self) -> int:
        return 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.received.append(texts)
        return [[float(len(t)), 1.0] for t in texts]


class _RaisingProvider(EmbeddingsProvider):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    @property
    def dim(self) -> int:
        return 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise self._exc


# ---------------------------------------------------------------------------
# Vocabulary (invariant 1)
# ---------------------------------------------------------------------------


def test_error_code_vocabulary_is_exactly_five() -> None:
    """REC-12 — ErrorCode is the registry of exactly the five wire codes;
    ``unknown_project`` is dropped (ADR-0014)."""
    assert {c.value for c in ErrorCode} == set(_CODES)
    assert len(ErrorCode) == 5
    assert "unknown_project" not in {c.value for c in ErrorCode}


def test_error_code_members_are_strings() -> None:
    """REC-12 — a StrEnum member is a ``str``, so equality and json.dumps keep the wire shape."""
    for code in ErrorCode:
        assert isinstance(code, str)
        assert code == code.value
        assert json.dumps(code) == json.dumps(code.value)


def test_no_error_code_literal_outside_errors_module() -> None:
    """REC-12 invariant 1 — the LLD §3.4 grep: no code literal appears in ``src/recall``
    outside ``errors.py``."""
    pattern = re.compile(r'"(' + "|".join(_CODES) + r')"')
    offenders = [
        f"{path.relative_to(_SRC)}:{lineno}: {line.strip()}"
        for path in sorted(_SRC.rglob("*.py"))
        if path.name != "errors.py"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        pytest.param(UnauthenticatedError(), ErrorCode.UNAUTHENTICATED, id="unauthenticated"),
        pytest.param(ValidationError("bad field"), ErrorCode.VALIDATION_ERROR, id="validation"),
        pytest.param(NotFoundError("abc"), ErrorCode.NOT_FOUND, id="not_found"),
    ],
)
def test_recall_error_subclasses_use_error_code(exc: RecallError, code: ErrorCode) -> None:
    """REC-12 AC1 — every RecallError subclass carries an ErrorCode member as ``error``."""
    assert isinstance(exc.error, ErrorCode)
    assert exc.error == code
    assert exc.hint


def test_validation_error_str_is_still_the_detail() -> None:
    """REC-12 invariant 5 — ``str(ValidationError)`` keeps returning the detail."""
    assert str(ValidationError("title must be a non-empty string")) == (
        "title must be a non-empty string"
    )


class TestEmbeddingError:
    """REC-12 AC2 — EmbeddingError shape."""

    def test_is_recall_error_with_embedding_failed_code(self) -> None:
        exc = EmbeddingError()
        assert isinstance(exc, RecallError)
        assert isinstance(exc.error, ErrorCode)
        assert exc.error == ErrorCode.EMBEDDING_FAILED
        assert json.dumps({"error": exc.error}) == '{"error": "embedding_failed"}'

    def test_hint_is_fixed_and_actionable(self) -> None:
        """The hint is the same for every failure (no cause interpolated) and tells the
        agent to retry, then escalate to the operator."""
        first, second = EmbeddingError(), EmbeddingError()
        assert first.hint == second.hint
        assert first.hint.strip()
        assert "retry" in first.hint.lower()
        assert "operator" in first.hint.lower()


# ---------------------------------------------------------------------------
# guarded_embed (unit)
# ---------------------------------------------------------------------------


class TestGuardedEmbed:
    """REC-12 BDD — guarded_embed passes vectors through and wraps provider failures."""

    def test_passes_vectors_through(self) -> None:
        stub = StubEmbeddingsProvider(dim=8)
        texts = ["alpha", "beta"]
        assert guarded_embed(stub)(texts) == stub.embed(texts)

    def test_passes_a_list_to_the_provider(self) -> None:
        """The store hands any Sequence; the provider contract is ``list[str]``."""
        provider = _ListProvider()
        vectors = guarded_embed(provider)(("a", "bcd"))
        assert vectors == [[1.0, 1.0], [3.0, 1.0]]
        assert provider.received == [["a", "bcd"]]
        assert isinstance(provider.received[0], list)

    def test_wraps_runtime_error(self) -> None:
        cause = RuntimeError(FAILING_PROVIDER_DETAIL)
        with pytest.raises(EmbeddingError) as info:
            guarded_embed(_RaisingProvider(cause))(["x"])
        assert info.value.error == ErrorCode.EMBEDDING_FAILED
        assert info.value.__cause__ is cause
        assert FAILING_PROVIDER_DETAIL not in info.value.hint
        assert FAILING_PROVIDER_DETAIL not in str(info.value)

    @pytest.mark.parametrize(
        "cause",
        [
            pytest.param(TimeoutError("timed out"), id="timeout"),
            pytest.param(ValueError("bad response"), id="value"),
            pytest.param(ConnectionError("unreachable"), id="connection"),
        ],
    )
    def test_wraps_any_provider_exception(self, cause: Exception) -> None:
        """Story 1.3 AC4 — unreachable / timed-out / erroring providers all surface as
        embedding_failed."""
        with pytest.raises(EmbeddingError) as info:
            guarded_embed(_RaisingProvider(cause))(["x"])
        assert info.value.__cause__ is cause

    def test_logs_cause_server_side(self, captured_logs: Logs) -> None:
        """The cause is logged with its exception info at error level."""
        with pytest.raises(EmbeddingError):
            guarded_embed(_RaisingProvider(RuntimeError(FAILING_PROVIDER_DETAIL)))(["x"])
        errors = [e for e in captured_logs if e.get("log_level") == "error"]
        assert len(errors) == 1, captured_logs
        assert "exc_info" in errors[0]

    def test_success_does_not_log_errors(self, captured_logs: Logs) -> None:
        guarded_embed(StubEmbeddingsProvider(dim=4))(["ok"])
        assert [e for e in captured_logs if e.get("log_level") == "error"] == []


# ---------------------------------------------------------------------------
# Envelopes through the real router (invariant 2)
# ---------------------------------------------------------------------------


class _EnvelopeSources(NamedTuple):
    """The fixtures each envelope scenario draws on, bundled into one argument."""

    store: AsyncPostgresStore
    failing_embedding_store: AsyncPostgresStore
    failing_adapter: object
    unauthenticated_client: _PerCallClient


@pytest.fixture
def envelope_sources(
    store: AsyncPostgresStore,
    failing_embedding_store: AsyncPostgresStore,
    failing_adapter: object,
    unauthenticated_client: _PerCallClient,
) -> _EnvelopeSources:
    return _EnvelopeSources(store, failing_embedding_store, failing_adapter, unauthenticated_client)


@pytest.mark.integration
class TestErrorEnvelopes:
    """REC-12 BDD — each of the five codes, produced through the real router, is
    exactly ``{error, hint}``."""

    @pytest.mark.parametrize("code", _CODES)
    async def test_envelope_shape(self, code: str, envelope_sources: _EnvelopeSources) -> None:
        (store, failing_embedding_store, failing_adapter, unauthenticated_client) = envelope_sources
        good = _router(store)
        scenarios: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
            "unauthenticated": lambda: unauthenticated_client.call_tool(
                "memory_save", _save_params()
            ),
            "validation_error": lambda: good.handle_tool_call(
                "memory_save", _save_params(content=""), "alice"
            ),
            "not_found": lambda: good.handle_tool_call(
                "memory_get", _locator(str(uuid.uuid4())), "alice"
            ),
            "embedding_failed": lambda: _router(failing_embedding_store).handle_tool_call(
                "memory_save", _save_params(), "alice"
            ),
            "internal_error": lambda: ToolRouter(
                MemoryService(cast("StorageAdapter", failing_adapter))
            ).handle_tool_call("memory_search", {"query": "q", "project_id": _PROJECT}, "alice"),
        }

        result = await scenarios[code]()

        _assert_envelope(result, code)


# ---------------------------------------------------------------------------
# embedding_failed on every embedding path (Story 1.3 AC4)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEmbeddingFailure:
    """REC-12 AC2/AC3 — provider failures surface as embedding_failed; nothing half-written."""

    async def test_embedding_failure_on_save(
        self,
        store: AsyncPostgresStore,
        failing_embedding_store: AsyncPostgresStore,
        pg_conn_string: str,
    ) -> None:
        """A failed save returns embedding_failed with the fixed hint and persists nothing."""
        result = await _router(failing_embedding_store).handle_tool_call(
            "memory_save", _save_params(), "alice"
        )

        assert result == {"error": "embedding_failed", "hint": EmbeddingError().hint}
        assert await _store_row_count(pg_conn_string) == 0

    async def test_failed_save_persists_nothing_global(
        self,
        store: AsyncPostgresStore,
        failing_embedding_store: AsyncPostgresStore,
        pg_conn_string: str,
    ) -> None:
        """Invariant 4 — global-scope saves are equally atomic."""
        params = _save_params(scope="global")
        del params["project_id"]

        result = await _router(failing_embedding_store).handle_tool_call(
            "memory_save", params, "alice"
        )

        assert result["error"] == "embedding_failed"
        assert await _store_row_count(pg_conn_string) == 0

    async def test_embedding_failure_on_update(
        self,
        store: AsyncPostgresStore,
        failing_embedding_store: AsyncPostgresStore,
        pg_conn_string: str,
    ) -> None:
        """A failed content update returns embedding_failed and leaves the record —
        content, updated_at and its vector — intact."""
        good = _router(store)
        saved = await good.handle_tool_call("memory_save", _save_params(), "alice")
        memory_id = saved["id"]
        before = await good.handle_tool_call("memory_get", _locator(memory_id), "alice")

        result = await _router(failing_embedding_store).handle_tool_call(
            "memory_update", {**_locator(memory_id), "content": "Replaced content."}, "alice"
        )

        assert result == {"error": "embedding_failed", "hint": EmbeddingError().hint}
        after = await good.handle_tool_call("memory_get", _locator(memory_id), "alice")
        assert after == before
        assert await _vector_row_count(pg_conn_string, memory_id) == 1

    async def test_update_without_content_change_does_not_embed(
        self, store: AsyncPostgresStore, failing_embedding_store: AsyncPostgresStore
    ) -> None:
        """Only a content change embeds, so a tags-only update succeeds even when the
        provider is down (Story 1.3 AC3)."""
        good = _router(store)
        memory_id = (await good.handle_tool_call("memory_save", _save_params(), "alice"))["id"]

        result = await _router(failing_embedding_store).handle_tool_call(
            "memory_update", {**_locator(memory_id), "tags": ["billing"]}, "alice"
        )

        assert result == {"id": memory_id}
        record = await good.handle_tool_call("memory_get", _locator(memory_id), "alice")
        assert record["tags"] == ["billing"]

    @pytest.mark.parametrize("scope", [None, "project", "global"])
    async def test_embedding_failure_on_search(
        self,
        failing_embedding_store: AsyncPostgresStore,
        store: AsyncPostgresStore,
        scope: str | None,
    ) -> None:
        """The store embeds the query through the same guarded function, so search
        (merged or explicit scope) returns embedding_failed, not internal_error."""
        params: dict[str, Any] = {"query": "event sourcing", "project_id": _PROJECT}
        if scope is not None:
            params["scope"] = scope

        result = await _router(failing_embedding_store).handle_tool_call(
            "memory_search", params, "alice"
        )

        assert result == {"error": "embedding_failed", "hint": EmbeddingError().hint}

    async def test_embedding_failure_does_not_leak_cause(
        self,
        store: AsyncPostgresStore,
        failing_embedding_store: AsyncPostgresStore,
        captured_logs: Logs,
    ) -> None:
        """Invariant 3 — save, update and search envelopes never carry the provider's
        message or type; the cause is logged server-side and the mcp_call event
        records embedding_failed."""
        memory_id = (await _router(store).handle_tool_call("memory_save", _save_params(), "alice"))[
            "id"
        ]
        failing = _router(failing_embedding_store)
        captured_logs.clear()

        results = [
            await failing.handle_tool_call("memory_save", _save_params(), "alice"),
            await failing.handle_tool_call(
                "memory_update", {**_locator(memory_id), "content": "New."}, "alice"
            ),
            await failing.handle_tool_call(
                "memory_search",
                {"query": "q", "project_id": _PROJECT, "scope": "project"},
                "alice",
            ),
        ]

        for result in results:
            _assert_envelope(result, "embedding_failed")
            _assert_no_leak(result)
        statuses = [e["result_status"] for e in captured_logs if e.get("event") == "mcp_call"]
        assert statuses == ["embedding_failed"] * 3
        assert any(e.get("log_level") == "error" and "exc_info" in e for e in captured_logs), (
            captured_logs
        )
        assert not [e for e in captured_logs if e.get("event") == "tool_internal_error"]


# ---------------------------------------------------------------------------
# Composition root wiring (server._build_store)
# ---------------------------------------------------------------------------


class _ExplodingStub(StubEmbeddingsProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(FAILING_PROVIDER_DETAIL)


@pytest.mark.integration
async def test_server_store_wires_guarded_embed(
    mcp_client: _PerCallClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REC-12 AC — ``server._build_store`` embeds through ``guarded_embed``: a provider
    failure in the running app surfaces over MCP as embedding_failed, not internal_error,
    and the cause does not leak."""
    monkeypatch.setattr("recall.server.StubEmbeddingsProvider", _ExplodingStub)

    result = await mcp_client.call_tool("memory_save", _save_params())

    _assert_envelope(result, "embedding_failed")
    _assert_no_leak(result)
