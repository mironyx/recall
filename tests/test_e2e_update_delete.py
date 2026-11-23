"""End-to-end tests for memory_update and memory_delete over real MCP transport.

Contract sources: issues REC-10 (E3.1b) and REC-11 (E3.2) BDD specs;
``docs/design/v2/lld-e3-update-delete-errors.md`` §3.2 and §3.3; requirements
Stories 1.3, 1.4, 1.5, 4.2, 4.3, 5.1. Real Postgres via testcontainers
(ADR-0012); the stub embedder makes identical text score identically and
unrelated text lower.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from typing import Any

import pytest

from tests.conftest import BOB_HEADERS, _PerCallClient
from tests.test_memory_service import _vector_row_count

PROJECT = "proj-e2e"


async def _save(client: _PerCallClient, **overrides: Any) -> str:
    params: dict[str, Any] = {
        "scope": "project",
        "project_id": PROJECT,
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    params.update(overrides)
    if params["scope"] == "global":
        del params["project_id"]
    payload = await client.call_tool("memory_save", params)
    assert "id" in payload, payload
    return str(payload["id"])


def _upd(memory_id: str, **fields: Any) -> dict[str, Any]:
    return {"scope": "project", "project_id": PROJECT, "id": memory_id, **fields}


async def _get(client: _PerCallClient, memory_id: str) -> dict[str, Any]:
    return await client.call_tool(
        "memory_get", {"scope": "project", "project_id": PROJECT, "id": memory_id}
    )


async def _search(client: _PerCallClient, query: str) -> list[dict[str, Any]]:
    out = await client.call_tool("memory_search", {"project_id": PROJECT, "query": query})
    return list(out["results"])


@pytest.mark.integration
class TestMemoryUpdateTool:
    async def test_content_update_round_trips_through_get_and_search(
        self, mcp_client: _PerCallClient
    ) -> None:
        mid = await _save(mcp_client)
        new_text = "Completely different quokka telemetry pipeline notes."
        out = await mcp_client.call_tool("memory_update", _upd(mid, content=new_text))
        assert out == {"id": mid}
        record = await _get(mcp_client, mid)
        assert record["content"] == new_text
        assert record["updated_at"] >= record["created_at"]
        results = await _search(mcp_client, new_text)
        assert results[0]["id"] == mid

    async def test_metadata_only_update_keeps_search_ranking(
        self, mcp_client: _PerCallClient
    ) -> None:
        a = await _save(mcp_client, content="Alpha deployment pipeline text.")
        await _save(mcp_client, content="Unrelated lunch menu 12345.")
        before = await _search(mcp_client, "Alpha deployment pipeline text.")
        out = await mcp_client.call_tool("memory_update", _upd(a, metadata={"k": "v"}))
        assert out == {"id": a}
        after = await _search(mcp_client, "Alpha deployment pipeline text.")
        assert [(r["id"], r["score"]) for r in after] == [(r["id"], r["score"]) for r in before]
        assert (await _get(mcp_client, a))["metadata"] == {"k": "v"}

    async def test_title_update(self, mcp_client: _PerCallClient) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool("memory_update", _upd(mid, title="Renamed"))
        assert out == {"id": mid}
        record = await _get(mcp_client, mid)
        assert record["title"] == "Renamed"
        assert record["content"] == "The billing service uses event sourcing."

    async def test_global_memory_update_with_sentinel_project_id(
        self, mcp_client: _PerCallClient
    ) -> None:
        mid = await _save(mcp_client, scope="global")
        out = await mcp_client.call_tool(
            "memory_update", {"scope": "global", "project_id": "_", "id": mid, "title": "G2"}
        )
        assert out == {"id": mid}

    async def test_empty_payload_rejected(self, mcp_client: _PerCallClient) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool("memory_update", _upd(mid))
        assert out["error"] == "validation_error"
        for name in ("title", "content", "tags", "metadata"):
            assert name in out["hint"]

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("kind", "gotcha"),
            ("user_id", "bob"),
            ("created_at", "2020-01-01T00:00:00Z"),
            ("updated_at", "2020-01-01T00:00:00Z"),
        ],
    )
    async def test_immutable_field_rejected(
        self, mcp_client: _PerCallClient, field: str, value: str
    ) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool("memory_update", _upd(mid, title="T2", **{field: value}))
        assert out["error"] == "validation_error"
        assert field in out["hint"]
        assert (await _get(mcp_client, mid))["title"] == "Use event sourcing"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("title", ""),
            ("title", 5),
            ("content", ""),
            ("content", 3),
            ("tags", "a"),
            ("tags", [1]),
            ("metadata", ["x"]),
            ("metadata", "x"),
        ],
    )
    async def test_bad_types_rejected(
        self, mcp_client: _PerCallClient, field: str, value: Any
    ) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool("memory_update", _upd(mid, **{field: value}))
        assert out["error"] == "validation_error"
        assert field in out["hint"]

    async def test_empty_tags_and_metadata_clear_the_fields(
        self, mcp_client: _PerCallClient
    ) -> None:
        mid = await _save(mcp_client, tags=["a", "b"], metadata={"k": 1})
        out = await mcp_client.call_tool("memory_update", _upd(mid, tags=[], metadata={}))
        assert out == {"id": mid}
        record = await _get(mcp_client, mid)
        assert record["tags"] == []
        assert record["metadata"] == {}

    async def test_null_means_not_supplied(self, mcp_client: _PerCallClient) -> None:
        mid = await _save(mcp_client, tags=["keep"])
        out = await mcp_client.call_tool(
            "memory_update",
            _upd(mid, title="New title", content=None, tags=None, metadata=None),
        )
        assert out == {"id": mid}
        record = await _get(mcp_client, mid)
        assert record["title"] == "New title"
        assert record["content"] == "The billing service uses event sourcing."
        assert record["tags"] == ["keep"]

    async def test_all_null_is_an_empty_payload(self, mcp_client: _PerCallClient) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool(
            "memory_update", _upd(mid, title=None, content=None, tags=None, metadata=None)
        )
        assert out["error"] == "validation_error"

    @pytest.mark.parametrize("missing", ["scope", "project_id", "id"])
    async def test_missing_locator_rejected(self, mcp_client: _PerCallClient, missing: str) -> None:
        params = _upd(str(uuid.uuid4()), title="T")
        del params[missing]
        out = await mcp_client.call_tool("memory_update", params)
        assert out["error"] == "validation_error"
        assert missing in out["hint"]

    async def test_unknown_id_is_not_found(self, mcp_client: _PerCallClient) -> None:
        out = await mcp_client.call_tool("memory_update", _upd(str(uuid.uuid4()), title="T"))
        assert out["error"] == "not_found"
        assert out["hint"]

    async def test_cross_namespace_id_is_not_found(self, mcp_client: _PerCallClient) -> None:
        mid = await _save(mcp_client)
        out = await mcp_client.call_tool(
            "memory_update",
            {"scope": "project", "project_id": "other-proj", "id": mid, "title": "Hijack"},
        )
        assert out["error"] == "not_found"
        out = await mcp_client.call_tool(
            "memory_update", {"scope": "global", "project_id": "_", "id": mid, "title": "Hijack"}
        )
        assert out["error"] == "not_found"
        assert (await _get(mcp_client, mid))["title"] == "Use event sourcing"

    async def test_update_does_not_change_author(self, mcp_client: _PerCallClient) -> None:
        """Invariant 1 — alice saves, bob updates, user_id is still alice."""
        mid = await _save(mcp_client)
        out = await mcp_client.as_user(BOB_HEADERS).call_tool(
            "memory_update", _upd(mid, title="Edited by bob")
        )
        assert out == {"id": mid}
        record = await _get(mcp_client, mid)
        assert record["user_id"] == "alice"
        assert record["title"] == "Edited by bob"

    async def test_update_requires_auth(self, unauthenticated_client: _PerCallClient) -> None:
        out = await unauthenticated_client.call_tool(
            "memory_update", _upd(str(uuid.uuid4()), title="T")
        )
        assert out["error"] == "unauthenticated"

    async def test_logs_one_mcp_call_per_update(
        self,
        mcp_client: _PerCallClient,
        captured_logs: list[MutableMapping[str, Any]],
    ) -> None:
        mid = await _save(mcp_client)
        await mcp_client.call_tool("memory_update", _upd(mid, title="T2"))
        await mcp_client.call_tool("memory_update", _upd(str(uuid.uuid4()), title="T3"))
        calls = [
            e
            for e in captured_logs
            if e.get("event") == "mcp_call" and e.get("tool") == "memory_update"
        ]
        assert [e["result_status"] for e in calls] == ["ok", "not_found"]
        assert calls[0]["project_id"] == PROJECT


@pytest.mark.integration
class TestMemoryUpdateToolListing:
    async def test_schema_and_description(self, mcp_client: _PerCallClient) -> None:
        tools = {t.name: t for t in await mcp_client.list_tools()}
        assert len(tools) <= 6
        tool = tools["memory_update"]
        schema = tool.input_schema
        assert set(schema["properties"]) == {
            "scope", "project_id", "id", "title", "content", "tags", "metadata",
        }  # fmt: skip
        assert set(schema["required"]) == {"scope", "project_id", "id"}
        desc = (tool.description or "").lower()
        for phrase in ("memory_save", "replace", "embed", "kind", "project_id", '"_"', "delete"):
            assert phrase in desc, phrase


# ---------------------------------------------------------------------------
# memory_delete — REC-11 (E3.2), LLD §3.3 anchor LLD-e3-delete
# ---------------------------------------------------------------------------


def _del(memory_id: str, **overrides: Any) -> dict[str, Any]:
    return {"scope": "project", "project_id": PROJECT, "id": memory_id, **overrides}


@pytest.mark.integration
class TestMemoryDeleteTool:
    async def test_deleted_memory_absent_from_get_and_search(
        self, mcp_client: _PerCallClient
    ) -> None:
        """REC-11 invariant 1 — get is not_found; search never returns the id."""
        text = "Ephemeral wombat cache notes to delete."
        mid = await _save(mcp_client, content=text)
        assert (await _search(mcp_client, text))[0]["id"] == mid

        out = await mcp_client.call_tool("memory_delete", _del(mid))

        assert out == {"ok": True}
        assert (await _get(mcp_client, mid))["error"] == "not_found"
        assert mid not in [r["id"] for r in await _search(mcp_client, text)]

    async def test_global_memory_deleted_with_sentinel_project_id(
        self, mcp_client: _PerCallClient
    ) -> None:
        """REC-11 — global memories are addressed with project_id '_'."""
        mid = await _save(mcp_client, scope="global")

        out = await mcp_client.call_tool(
            "memory_delete", {"scope": "global", "project_id": "_", "id": mid}
        )

        assert out == {"ok": True}
        got = await mcp_client.call_tool(
            "memory_get", {"scope": "global", "project_id": "_", "id": mid}
        )
        assert got["error"] == "not_found"

    async def test_delete_removes_embedding_row(
        self, mcp_client: _PerCallClient, pg_conn_string: str
    ) -> None:
        """REC-11 invariant 2 — no store_vectors row remains for the key."""
        mid = await _save(mcp_client)
        assert await _vector_row_count(pg_conn_string, mid, f"project.{PROJECT}") == 1

        await mcp_client.call_tool("memory_delete", _del(mid))

        assert await _vector_row_count(pg_conn_string, mid, f"project.{PROJECT}") == 0

    async def test_delete_is_idempotent(self, mcp_client: _PerCallClient) -> None:
        """REC-11 invariant 3 — an absent id returns ok, twice in a row."""
        mid = str(uuid.uuid4())

        assert await mcp_client.call_tool("memory_delete", _del(mid)) == {"ok": True}
        assert await mcp_client.call_tool("memory_delete", _del(mid)) == {"ok": True}

    async def test_delete_existing_twice_is_ok(self, mcp_client: _PerCallClient) -> None:
        """REC-11 Story 1.5 AC3 — re-deleting a deleted memory is not an error."""
        mid = await _save(mcp_client)

        assert await mcp_client.call_tool("memory_delete", _del(mid)) == {"ok": True}
        assert await mcp_client.call_tool("memory_delete", _del(mid)) == {"ok": True}

    async def test_delete_wrong_namespace_leaves_memory(self, mcp_client: _PerCallClient) -> None:
        """REC-11 invariant 4 — delete in another namespace returns ok but removes nothing."""
        mid = await _save(mcp_client)

        out = await mcp_client.call_tool("memory_delete", _del(mid, project_id="other-proj"))
        assert out == {"ok": True}
        out = await mcp_client.call_tool(
            "memory_delete", {"scope": "global", "project_id": "_", "id": mid}
        )
        assert out == {"ok": True}

        assert (await _get(mcp_client, mid))["id"] == mid

    @pytest.mark.parametrize(
        ("scope", "project_id"),
        [("global", PROJECT), ("project", "_"), ("team", PROJECT)],
    )
    async def test_delete_scope_invariant_enforced(
        self, mcp_client: _PerCallClient, scope: str, project_id: str
    ) -> None:
        """REC-11 invariant 5 — invalid scope pairing is a validation_error; nothing removed."""
        mid = await _save(mcp_client)

        out = await mcp_client.call_tool(
            "memory_delete", {"scope": scope, "project_id": project_id, "id": mid}
        )

        assert out["error"] == "validation_error"
        assert out["hint"]
        assert (await _get(mcp_client, mid))["id"] == mid

    @pytest.mark.parametrize("missing", ["scope", "project_id", "id"])
    async def test_missing_fields_rejected(self, mcp_client: _PerCallClient, missing: str) -> None:
        """REC-11 — a missing locator field is a validation_error naming it."""
        params = _del(str(uuid.uuid4()))
        del params[missing]

        out = await mcp_client.call_tool("memory_delete", params)

        assert out["error"] == "validation_error"
        assert missing in out["hint"]

    @pytest.mark.parametrize("field", ["scope", "project_id", "id"])
    async def test_empty_fields_rejected(self, mcp_client: _PerCallClient, field: str) -> None:
        """REC-11 — empty strings are treated as missing (Story 1.1 AC4 convention)."""
        out = await mcp_client.call_tool("memory_delete", _del(str(uuid.uuid4()), **{field: ""}))

        assert out["error"] == "validation_error"

    @pytest.mark.parametrize(
        ("field", "value"),
        [("id", 123), ("id", ["x"]), ("scope", 1), ("project_id", {"p": 1})],
    )
    async def test_non_string_fields_rejected(
        self, mcp_client: _PerCallClient, field: str, value: Any
    ) -> None:
        """REC-11 — a non-string locator is a validation_error, never internal_error."""
        out = await mcp_client.call_tool("memory_delete", _del(str(uuid.uuid4()), **{field: value}))

        assert out["error"] == "validation_error"

    async def test_any_user_can_delete(self, mcp_client: _PerCallClient) -> None:
        """REC-11 — memories are shared within a project (Story 5.2); bob deletes alice's."""
        mid = await _save(mcp_client)

        out = await mcp_client.as_user(BOB_HEADERS).call_tool("memory_delete", _del(mid))

        assert out == {"ok": True}
        assert (await _get(mcp_client, mid))["error"] == "not_found"

    async def test_delete_requires_auth(
        self, mcp_client: _PerCallClient, unauthenticated_client: _PerCallClient
    ) -> None:
        """REC-11 — no bearer token: unauthenticated, and the memory survives."""
        mid = await _save(mcp_client)

        out = await unauthenticated_client.call_tool("memory_delete", _del(mid))

        assert out["error"] == "unauthenticated"
        assert (await _get(mcp_client, mid))["id"] == mid

    async def test_logs_one_mcp_call_per_delete(
        self,
        mcp_client: _PerCallClient,
        captured_logs: list[MutableMapping[str, Any]],
    ) -> None:
        """REC-11 — each delete emits exactly one mcp_call event (ADR-0011)."""
        mid = await _save(mcp_client)
        await mcp_client.call_tool("memory_delete", _del(mid))
        await mcp_client.call_tool("memory_delete", {"scope": "project", "project_id": PROJECT})

        calls = [
            e
            for e in captured_logs
            if e.get("event") == "mcp_call" and e.get("tool") == "memory_delete"
        ]
        assert [e["result_status"] for e in calls] == ["ok", "validation_error"]
        assert calls[0]["project_id"] == PROJECT
        assert calls[0]["scope"] == "project"
        assert calls[0]["user_id"] == "alice"


@pytest.mark.integration
class TestMemoryDeleteToolListing:
    async def test_schema_and_description(self, mcp_client: _PerCallClient) -> None:
        """REC-11 Story 4.2 — declared tool: schema and agent-oriented description."""
        tools = {t.name: t for t in await mcp_client.list_tools()}
        assert len(tools) <= 6
        tool = tools["memory_delete"]
        schema = tool.input_schema
        assert set(schema["properties"]) == {"scope", "project_id", "id"}
        assert set(schema["required"]) == {"scope", "project_id", "id"}
        desc = (tool.description or "").lower()
        assert "permanent" in desc
        assert "idempotent" in desc
        assert '"_"' in desc
        assert "global" in desc
        assert "memory_update" in desc

    def test_server_constants_match_listing(self) -> None:
        """REC-11 — the description and schema are module constants in server.py."""
        from recall.server import MEMORY_DELETE_DESCRIPTION, MEMORY_DELETE_SCHEMA

        assert "permanent" in MEMORY_DELETE_DESCRIPTION.lower()
        assert MEMORY_DELETE_SCHEMA["type"] == "object"
        assert set(MEMORY_DELETE_SCHEMA["required"]) == {"scope", "project_id", "id"}
