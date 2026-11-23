"""MCP tool registration, dispatch, validation, and error formatting."""

from __future__ import annotations

import time
from typing import Any, NamedTuple

import structlog

from recall.errors import ErrorCode, RecallError, ValidationError
from recall.memory_service import MemoryService
from recall.storage_adapter import GLOBAL_SENTINEL
from recall.validation import validate_project_id_format

log = structlog.get_logger()

_MAX_QUERY_CHARS = 2000
_INTERNAL_HINT = "An unexpected error occurred. Retry; if it persists, contact the server operator."


class _SearchParams(NamedTuple):
    query: str
    project_id: str
    scope: str | None
    kind: str | None
    author_user_id: str | None  # wire "user_id": the memory's author, not the caller
    limit: int | None


_LOCATOR_FIELDS = ("scope", "project_id", "id")
_IMMUTABLE_UPDATE_FIELDS = ("kind", "user_id", "created_at", "updated_at")


class _UpdateParams(NamedTuple):
    scope: str
    project_id: str
    memory_id: str
    title: str | None
    content: str | None
    tags: list[str] | None
    metadata: dict[str, Any] | None


def _check_text(name: str, value: object) -> None:
    """None = not supplied; otherwise a non-empty string is required."""
    if value is not None and (not isinstance(value, str) or not value):
        raise ValidationError(f"{name} must be a non-empty string")


def _check_update_types(params: dict[str, Any]) -> None:
    """Type-check the update fields (``[]``/``{}`` valid, None = absent)."""
    for name in ("scope", "project_id", "id", "title", "content"):
        _check_text(name, params.get(name))
    tags = params.get("tags")
    if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        raise ValidationError("tags must be a list of strings")
    metadata = params.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValidationError("metadata must be an object")


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
            RecallError maps to its own {error, hint}; any other exception is
            logged server-side and returned as a general internal_error with
            no cause or stack trace (Story 4.3 AC4).
        """
        start = time.monotonic()
        try:
            result = await self._dispatch(tool_name, params, user_id)
        except RecallError as exc:
            self._log_call(tool_name, params, user_id, start, exc.error)
            return {"error": exc.error, "hint": exc.hint}
        except Exception:
            log.exception("tool_internal_error", tool=tool_name)
            self._log_call(tool_name, params, user_id, start, ErrorCode.INTERNAL_ERROR)
            return {"error": ErrorCode.INTERNAL_ERROR, "hint": _INTERNAL_HINT}
        results = result.get("results")
        count = len(results) if isinstance(results, list) else None
        self._log_call(tool_name, params, user_id, start, "ok", count)
        return result

    @staticmethod
    def _log_call(
        tool_name: str,
        params: dict[str, Any],
        user_id: str,
        start: float,
        result_status: str,
        result_count: int | None = None,
    ) -> None:
        """Emit the single mcp_call event for this tool call (ADR-0011).

        Justification (CodeScene: excess function arguments): the six
        arguments map one-to-one onto event fields; bundling them into a
        context object would add a wrapper type for few call sites, against
        the project's simplicity-first rule (CLAUDE.md).
        ``request_id`` arrives via the structlog context (RequestContextMiddleware).
        """
        extra: dict[str, Any] = {} if result_count is None else {"result_count": result_count}
        log.info(
            "mcp_call",
            tool=tool_name,
            user_id=user_id,
            # project_id may be absent for global-scope calls or validation
            # failures before scope resolution; the event stays well-formed.
            project_id=params.get("project_id", ""),
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            kind=params.get("kind", ""),
            scope=params.get("scope", ""),
            result_status=result_status,
            **extra,
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
        if tool_name == "memory_search":
            return await self._handle_memory_search(params)
        if tool_name == "memory_update":
            return await self._handle_memory_update(params)
        if tool_name == "memory_delete":
            return await self._handle_memory_delete(params)
        raise ValidationError(f"Unknown tool: {tool_name}")

    async def _handle_memory_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and delegate memory_delete (Story 1.5); idempotent."""
        missing = self._missing_fields(params, _LOCATOR_FIELDS)
        if missing:
            raise ValidationError(f"Missing required field: {missing[0]}")
        for name in _LOCATOR_FIELDS:
            _check_text(name, params[name])
        await self._memory_service.delete(params["scope"], params["project_id"], params["id"])
        return {"ok": True}

    async def _handle_memory_update(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and delegate memory_update.

        The authenticated caller is deliberately not a parameter: it must not
        reach ``update`` (the author is immutable, Story 1.4).
        """
        p = self._parse_update_params(params)
        memory_id = await self._memory_service.update(
            p.scope, p.project_id, p.memory_id, p.title, p.content, p.tags, p.metadata
        )
        return {"id": memory_id}

    @staticmethod
    def _parse_update_params(params: dict[str, Any]) -> _UpdateParams:
        """Validate memory_update params at the boundary (Story 1.4, 4.2).

        ``None`` means "not supplied"; ``[]`` and ``{}`` are valid and clear
        the field, so ``_missing_fields`` (which treats them as missing) is
        not used for the optional fields.
        """
        missing = ToolRouter._missing_fields(params, _LOCATOR_FIELDS)
        if missing:
            raise ValidationError(f"Missing required field: {missing[0]}")
        for name in _IMMUTABLE_UPDATE_FIELDS:
            if name in params:
                raise ValidationError(f"Field '{name}' is immutable and cannot be updated")
        _check_update_types(params)
        return _UpdateParams(
            params["scope"], params["project_id"], params["id"],
            params.get("title"), params.get("content"),
            params.get("tags"), params.get("metadata"),
        )  # fmt: skip

    async def _handle_memory_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate and delegate memory_search.

        The authenticated caller is deliberately not a parameter: it must not
        reach ``search`` (Story 5.2 AC3 — memories are shared within a project).
        """
        p = self._parse_search_params(params)
        # The service takes a consistent (scope, project_id) pair; global
        # memories live under the sentinel (ADR-0002), so map it here.
        results = await self._memory_service.search(
            project_id=GLOBAL_SENTINEL if p.scope == "global" else p.project_id,
            query=p.query,
            scope=p.scope,
            kind=p.kind,
            author_user_id=p.author_user_id,
            limit=p.limit,
        )
        return {"results": [r.model_dump() for r in results]}

    @staticmethod
    def _parse_search_params(params: dict[str, Any]) -> _SearchParams:
        """Validate memory_search params at the boundary (Story 2.x, 4.3)."""
        query = params.get("query", "")
        if not isinstance(query, str) or not query:
            raise ValidationError("Missing required field: query")
        if len(query) > _MAX_QUERY_CHARS:
            raise ValidationError(f"query exceeds {_MAX_QUERY_CHARS} characters")
        project_id = params.get("project_id", "")
        validate_project_id_format(project_id)
        scope = params.get("scope")
        if scope not in (None, "project", "global"):
            raise ValidationError(f"Invalid scope: {scope}")
        limit = params.get("limit")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)):
            raise ValidationError("limit must be an integer")
        return _SearchParams(
            query, project_id, scope, params.get("kind"), params.get("user_id"), limit
        )

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
