"""MCP tool registration, dispatch, validation, and error formatting."""

from __future__ import annotations

import time
from typing import Any

import structlog

from recall.errors import RecallError, ValidationError
from recall.memory_service import MemoryService
from recall.storage_adapter import GLOBAL_SENTINEL
from recall.validation import validate_project_id_format

log = structlog.get_logger()


class ToolRouter:
    """Registers MCP tools and dispatches calls with cross-cutting concerns.

    Responsibilities:
    - Validate common parameters (scope, project_id)
    - Dispatch to MemoryService
    - Catch RecallError and format as structured MCP errors
    - Emit one mcp_call log event per call (ADR-0011)
    """

    def __init__(self, memory_service: MemoryService) -> None:
        self._memory_service = memory_service

    async def handle_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        """Dispatch a tool call with logging and error handling.

        Args:
            tool_name: The MCP tool name.
            params: The tool parameters.
            user_id: Resolved from auth.

        Returns:
            The tool result dict.

        Raises:
            Nothing — errors are caught and returned as structured dicts.
            Only RecallError is caught (Story 4.3 AC4); unexpected failures
            propagate to the transport layer.
        """
        start = time.monotonic()
        try:
            result = await self._dispatch(tool_name, params, user_id)
        except RecallError as exc:
            self._log_call(tool_name, params, user_id, start, exc.error)
            return {"error": exc.error, "hint": exc.hint}
        self._log_call(tool_name, params, user_id, start, "ok")
        return result

    @staticmethod
    def _log_call(
        tool_name: str,
        params: dict[str, Any],
        user_id: str,
        start: float,
        result_status: str,
    ) -> None:
        """Emit the single mcp_call event for this tool call (ADR-0011).

        Justification (CodeScene: excess function arguments): the five
        arguments are exactly the five event fields; bundling them into a
        context object would add a wrapper type for two call sites, against
        the project's simplicity-first rule (CLAUDE.md).
        """
        log.info(
            "mcp_call",
            tool=tool_name,
            user_id=user_id,
            # project_id may be absent for global-scope calls or validation
            # failures before scope resolution; the event stays well-formed.
            project_id=params.get("project_id", ""),
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            result_status=result_status,
        )

    async def _dispatch(
        self,
        tool_name: str,
        params: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        """Route to the appropriate service method."""
        if tool_name == "memory_save":
            return await self._handle_memory_save(params, user_id)
        if tool_name == "memory_get":
            return await self._handle_memory_get(params)
        raise ValidationError(f"Unknown tool: {tool_name}")

    async def _handle_memory_save(self, params: dict[str, Any], user_id: str) -> dict[str, Any]:
        """Validate and delegate memory_save."""
        # Story 1.1 AC4 — the boundary treats empty and missing alike.
        missing = self._missing_fields(params, ("scope", "kind", "title", "content"))
        if missing:
            raise ValidationError(f"Missing required field: {missing[0]}")

        scope, project_id = self._resolve_save_namespace(params)

        memory_id = await self._memory_service.save(
            scope=scope,
            project_id=project_id,
            user_id=user_id,
            kind=params.get("kind", ""),
            title=params.get("title", ""),
            content=params.get("content", ""),
            tags=params.get("tags"),
            metadata=params.get("metadata"),
        )
        return {"id": memory_id}

    async def _handle_memory_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and delegate memory_get."""
        # ADR-0015 — the (scope, project_id) namespace is explicit; all three
        # fields are required, empty and missing treated alike.
        if self._missing_fields(params, ("scope", "project_id", "id")):
            raise ValidationError("Missing required field: scope, project_id, id")

        return await self._memory_service.get_by_id(
            params.get("scope", ""),
            params.get("project_id", ""),
            params.get("id", ""),
        )

    @staticmethod
    def _missing_fields(params: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
        """Names of required fields that are empty or absent (Story 1.1 AC4).

        Justification: extracted so both handlers share the required-field
        check (the LLD inlines it per handler); removes the duplicate loop
        and the complex multi-field conditional (CodeScene, diag pass).
        """
        return [field_name for field_name in fields if not params.get(field_name, "")]

    @staticmethod
    def _resolve_save_namespace(params: dict[str, Any]) -> tuple[str, str]:
        """Resolve the (scope, project_id) namespace for a save call.

        Story 1.2 AC5 — scope is project|global only; Story 1.2 AC4 — the
        scope invariant: global memories never carry a project_id, project
        memories always resolve to one (ADR-0002). The saved record's
        project_id is GLOBAL_SENTINEL for global scope.
        """
        scope = params.get("scope", "")
        if scope not in ("project", "global"):
            raise ValidationError(f"Invalid scope: {scope}")

        if scope == "global":
            if params.get("project_id"):
                raise ValidationError("scope 'global' must not carry a project_id")
            return scope, GLOBAL_SENTINEL

        project_id = params.get("project_id", "")
        validate_project_id_format(project_id)
        return scope, project_id
