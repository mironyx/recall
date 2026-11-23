"""Tool-surface coverage over real MCP transport — Phase 3 exit (REC-13, E3.3b).

Contract sources: issue REC-13 BDD specs; ``docs/design/v2/lld-e3-update-delete-errors.md``
§3.5; requirements Stories 4.3 and 4.4. One happy and one error case per listed tool,
plus a guard that fails when a tool is listed without a row in ``TOOL_CASES``.

Error codes are string literals on purpose: this file must not depend on the
error-vocabulary registry (REC-12), only on the wire contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

import pytest

from tests.conftest import _PerCallClient

PROJECT = "proj-e2e"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
CONTENT = "The billing service uses event sourcing."


async def _save(client: _PerCallClient) -> str:
    payload = await client.call_tool(
        "memory_save",
        {
            "scope": "project",
            "project_id": PROJECT,
            "kind": "decision",
            "title": "Use event sourcing",
            "content": CONTENT,
        },
    )
    assert "id" in payload, payload
    return str(payload["id"])


def _locator(memory_id: str) -> dict[str, Any]:
    return {"scope": "project", "project_id": PROJECT, "id": memory_id}


# ---------------------------------------------------------------------------
# Happy paths — each seeds what it needs, calls the tool, asserts the success shape
# ---------------------------------------------------------------------------


async def _happy_save(client: _PerCallClient) -> dict[str, Any]:
    mid = await _save(client)
    assert mid
    return {"id": mid}


async def _happy_get(client: _PerCallClient) -> dict[str, Any]:
    mid = await _save(client)
    out = await client.call_tool("memory_get", _locator(mid))
    assert out["id"] == mid
    assert out["content"] == CONTENT
    return out


async def _happy_search(client: _PerCallClient) -> dict[str, Any]:
    mid = await _save(client)
    out = await client.call_tool("memory_search", {"project_id": PROJECT, "query": CONTENT})
    assert out["results"][0]["id"] == mid
    return out


async def _happy_update(client: _PerCallClient) -> dict[str, Any]:
    mid = await _save(client)
    out = await client.call_tool("memory_update", {**_locator(mid), "title": "Renamed"})
    assert out == {"id": mid}
    assert (await client.call_tool("memory_get", _locator(mid)))["title"] == "Renamed"
    return out


async def _happy_delete(client: _PerCallClient) -> dict[str, Any]:
    mid = await _save(client)
    out = await client.call_tool("memory_delete", _locator(mid))
    assert out == {"ok": True}
    assert (await client.call_tool("memory_get", _locator(mid)))["error"] == "not_found"
    return out


class ToolCases(NamedTuple):
    happy: Callable[[_PerCallClient], Awaitable[dict[str, Any]]]
    error: tuple[dict[str, Any], str]  # (params, expected wire error code)


TOOL_CASES: dict[str, ToolCases] = {
    "memory_save": ToolCases(
        happy=_happy_save,
        # title missing
        error=(
            {"scope": "project", "project_id": PROJECT, "kind": "decision", "content": CONTENT},
            "validation_error",
        ),
    ),
    "memory_get": ToolCases(happy=_happy_get, error=(_locator(UNKNOWN_ID), "not_found")),
    "memory_search": ToolCases(
        happy=_happy_search,
        # query missing
        error=({"project_id": PROJECT}, "validation_error"),
    ),
    "memory_update": ToolCases(
        happy=_happy_update,
        error=({**_locator(UNKNOWN_ID), "title": "T"}, "not_found"),
    ),
    "memory_delete": ToolCases(
        happy=_happy_delete,
        # id missing
        error=({"scope": "project", "project_id": PROJECT}, "validation_error"),
    ),
}


@pytest.mark.integration
class TestToolSurface:
    @pytest.mark.parametrize("tool", sorted(TOOL_CASES))
    async def test_happy_path(self, mcp_client: _PerCallClient, tool: str) -> None:
        payload = await TOOL_CASES[tool].happy(mcp_client)
        assert "error" not in payload, payload

    @pytest.mark.parametrize("tool", sorted(TOOL_CASES))
    async def test_error_path(self, mcp_client: _PerCallClient, tool: str) -> None:
        params, code = TOOL_CASES[tool].error
        out = await mcp_client.call_tool(tool, params)
        assert out["error"] == code, out
        assert out.get("hint"), out

    async def test_every_listed_tool_has_both_cases(self, mcp_client: _PerCallClient) -> None:
        names = {t.name for t in await mcp_client.list_tools()}
        assert names == set(TOOL_CASES)
