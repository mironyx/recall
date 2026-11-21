"""End-to-end tests for memory_search over real MCP transport (REC-6, E2.4).

Contract sources: issue REC-6 BDD specs; ``docs/design/v2/lld-e2-search.md``
§2.4; ADR-0010 (project boost); requirements Stories 2.1-2.3, 3.1, 4.2, 4.4,
5.2 AC3 and §Security. Real Postgres via testcontainers (ADR-0012); the stub
embedder makes identical text score identically and unrelated text lower.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any

import pytest

from tests.conftest import BOB_HEADERS, _PerCallClient

SECRET = "zebra-quartz-content-marker"


async def _save(client: _PerCallClient, **overrides: Any) -> str:
    params: dict[str, Any] = {
        "scope": "project",
        "project_id": "proj-e2e",
        "kind": "decision",
        "title": "Use event sourcing",
        "content": "The billing service uses event sourcing.",
    }
    params.update(overrides)
    if params["scope"] == "global":
        del params["project_id"]  # scope invariant: global carries no project_id
    payload = await client.call_tool("memory_save", params)
    assert "id" in payload, payload
    return str(payload["id"])


def _search(project_id: str, query: str, **extra: Any) -> dict[str, Any]:
    return {"project_id": project_id, "query": query, **extra}


@pytest.mark.integration
class TestMemorySearchTool:
    async def test_search_returns_merged_ranked_list(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        await _save(mcp_client)
        await _save(mcp_client, scope="global", content="Global event sourcing note.")
        out = await mcp_client.call_tool("memory_search", _search(project_id, "event sourcing"))
        scopes = {r["scope"] for r in out["results"]}
        assert scopes == {"project", "global"}
        scores = [r["score"] for r in out["results"]]
        assert scores == sorted(scores, reverse=True)

    async def test_result_shape_over_transport(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        await _save(mcp_client)
        out = await mcp_client.call_tool("memory_search", _search(project_id, "event sourcing"))
        assert set(out["results"][0]) == {
            "id", "scope", "project_id", "kind", "title", "snippet", "score",
        }  # fmt: skip

    async def test_empty_results_not_an_error(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        out = await mcp_client.call_tool("memory_search", _search(project_id, "anything"))
        assert out == {"results": []}

    async def test_kind_filter_over_transport(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        await _save(mcp_client, kind="instruction", title="Always lint")
        await _save(mcp_client, kind="decision")
        out = await mcp_client.call_tool(
            "memory_search", _search(project_id, "event sourcing", kind="instruction")
        )
        assert out["results"]
        assert {r["kind"] for r in out["results"]} == {"instruction"}

    async def test_scope_restriction_over_transport(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        await _save(mcp_client)
        await _save(mcp_client, scope="global")
        out = await mcp_client.call_tool(
            "memory_search", _search(project_id, "event sourcing", scope="global")
        )
        assert out["results"]
        assert {r["scope"] for r in out["results"]} == {"global"}

    async def test_caller_identity_is_not_the_author_filter(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        """Story 5.2 AC3 — alice's search returns bob's memories."""
        bob_id = await _save(mcp_client.as_user(BOB_HEADERS))
        out = await mcp_client.call_tool("memory_search", _search(project_id, "event sourcing"))
        assert bob_id in {r["id"] for r in out["results"]}

    async def test_wire_user_id_filters_by_author(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        bob_id = await _save(mcp_client.as_user(BOB_HEADERS))
        await _save(mcp_client)
        out = await mcp_client.call_tool(
            "memory_search", _search(project_id, "event sourcing", user_id="bob")
        )
        assert [r["id"] for r in out["results"]] == [bob_id]

    async def test_search_requires_auth(self, unauthenticated_client: _PerCallClient) -> None:
        out = await unauthenticated_client.call_tool(
            "memory_search", _search("proj-e2e", "anything")
        )
        assert out["error"] == "unauthenticated"

    @pytest.mark.parametrize(
        ("params", "needle"),
        [
            ({"project_id": "proj-e2e"}, "query"),
            ({"project_id": "Bad ID!", "query": "q"}, ""),
            ({"project_id": "proj-e2e", "query": "x" * 2001}, "2000"),
            ({"project_id": "proj-e2e", "query": "q", "scope": "team"}, "scope"),
            ({"project_id": "proj-e2e", "query": "q", "limit": "ten"}, "limit"),
        ],
    )
    async def test_invalid_params_rejected(
        self, mcp_client: _PerCallClient, params: dict[str, Any], needle: str
    ) -> None:
        out = await mcp_client.call_tool("memory_search", params)
        assert out["error"] == "validation_error"
        assert needle in out["hint"]

    async def test_content_and_query_never_logged_and_result_count_set(
        self,
        mcp_client: _PerCallClient,
        project_id: str,
        captured_logs: list[MutableMapping[str, Any]],
    ) -> None:
        await _save(mcp_client, title="Secret title", content=SECRET)
        out = await mcp_client.call_tool("memory_search", _search(project_id, SECRET))
        assert out["results"]
        blob = json.dumps(captured_logs, default=str)
        assert SECRET not in blob
        assert "Secret title" not in blob
        calls = [e for e in captured_logs if e.get("event") == "mcp_call"]
        search_call = calls[-1]
        assert search_call["tool"] == "memory_search"
        assert search_call["result_count"] == len(out["results"])


@pytest.mark.integration
class TestSearchRankingEndToEnd:
    """Phase 2 exit criterion — ADR-0010 properties over the real transport."""

    async def test_planted_tie_favours_project(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        text = "Identical tie text about deployment pipelines."
        await _save(mcp_client, scope="global", content=text)
        await _save(mcp_client, content=text)
        out = await mcp_client.call_tool("memory_search", _search(project_id, text))
        assert [r["scope"] for r in out["results"][:2]] == ["project", "global"]

    async def test_planted_strong_global_beats_weak_project(
        self, mcp_client: _PerCallClient, project_id: str
    ) -> None:
        query = "rotate credentials quarterly"
        await _save(mcp_client, scope="global", content=query)
        await _save(mcp_client, content="Completely unrelated lunch menu 12345.")
        out = await mcp_client.call_tool("memory_search", _search(project_id, query))
        assert out["results"][0]["scope"] == "global"


@pytest.mark.integration
class TestToolBudget:
    async def test_at_most_six_tools(self, mcp_client: _PerCallClient) -> None:
        tools = await mcp_client.list_tools()
        assert "memory_search" in {t.name for t in tools}
        assert len(tools) <= 6

    async def test_description_documents_scope_default(self, mcp_client: _PerCallClient) -> None:
        tools = {t.name: t for t in await mcp_client.list_tools()}
        desc = (tools["memory_search"].description or "").lower()
        for phrase in ("project", "global", "scope", "instruction", "empty list"):
            assert phrase in desc
        props = set(tools["memory_search"].input_schema["properties"])
        assert props == {"project_id", "query", "kind", "scope", "user_id", "limit"}
