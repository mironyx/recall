"""End-to-end tests for memory_update over real MCP transport (REC-10, E3.1b).

Contract sources: issue REC-10 BDD specs; ``docs/design/v2/lld-e3-update-delete-errors.md``
§3.2; requirements Stories 1.3, 1.4, 4.2, 4.3, 5.1. Real Postgres via
testcontainers (ADR-0012); the stub embedder makes identical text score
identically and unrelated text lower. ``TestMemoryDeleteTool`` (§3.3) extends
this file later.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from typing import Any

import pytest

from tests.conftest import BOB_HEADERS, _PerCallClient

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
