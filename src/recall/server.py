"""Recall HTTP server — Starlette ASGI app with health and MCP tool endpoints.

Phase 0 mounts ``/healthz`` and ``/readyz`` on the ASGI app plus a request-
context middleware that binds ``request_id``/``trace_id``/``span_id`` into the
structlog contextvar at the transport boundary. Phase 1 (E1.6, issue #91)
mounts the MCP Streamable HTTP endpoint (ADR-0006) at ``/mcp``: a lowlevel
MCP ``Server`` (2026-07-28 protocol revision) declares
``memory_save``/``memory_get``; its dispatcher task group runs in the app
lifespan, serving requests through the SDK's Streamable HTTP ASGI app.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from recall.auth import AuthConfig, authenticate, load_auth_config
from recall.config import SearchConfig
from recall.db.schema import describe_db_error
from recall.embeddings.provider import guarded_embed, validate_dim
from recall.embeddings.stub import StubEmbeddingsProvider
from recall.errors import UnauthenticatedError
from recall.health import healthz, readyz
from recall.logging import bind_request_context, unbind_request_context
from recall.memory_service import MemoryService
from recall.storage_adapter import StorageAdapter
from recall.telemetry import get_trace_context
from recall.tool_router import ToolRouter

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from langgraph.store.postgres import AsyncPostgresStore

    from recall.settings import Settings

_log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MCP tool declarations (LLD §LLD-e1-mcp-tool-declarations; Story 4.2)
# ---------------------------------------------------------------------------

MEMORY_SAVE_DESCRIPTION = (
    "Store a new memory. Use this when the agent learns something worth "
    "remembering across sessions: a decision, convention, gotcha, or "
    "any other durable fact.\n\n"
    "Scope decision rule: if this fact would still be true and useful "
    "in a brand-new empty repo tomorrow, use scope='global'. Otherwise "
    "use scope='project'. When in doubt, prefer 'project'.\n\n"
    "Parameters:\n"
    "- scope (required): 'project' or 'global'\n"
    "- project_id (required if scope='project'): the project identifier\n"
    "- kind (required): category — e.g. 'decision', 'convention', "
    "'gotcha', 'component', 'episode', 'instruction'\n"
    "- title (required): short descriptive title\n"
    "- content (required): the full memory content\n"
    "- tags (optional): list of string tags\n"
    "- metadata (optional): additional key-value pairs"
)

MEMORY_SAVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["project", "global"]},
        "project_id": {"type": "string"},
        "kind": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
    },
    "required": ["scope", "kind", "title", "content"],
}

MEMORY_GET_DESCRIPTION = (
    "Fetch the complete record of a memory by its ID. Use this after "
    "finding a memory via memory_search to read the full content "
    "(search returns snippets only).\n\n"
    "Parameters:\n"
    '- scope (required): "project" or "global" — the memory\'s scope\n'
    '- project_id (required): the project the memory belongs to ("_"\n'
    "  for global)\n"
    "- id (required): the memory ID returned by memory_save or memory_search"
)

MEMORY_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["project", "global"]},
        "project_id": {"type": "string"},
        "id": {"type": "string"},
    },
    "required": ["scope", "project_id", "id"],
}

MEMORY_SEARCH_DESCRIPTION = (
    "Semantic search over stored memories. Call this at the start of a task, "
    "and whenever you need prior decisions, conventions, gotchas or "
    "instructions, BEFORE re-deriving them or asking the user.\n\n"
    "By default it searches the project's memories AND global memories "
    "together and returns one ranked list (project hits get a small boost). "
    "Pass scope to restrict to one of them. To load standing guidance, use "
    "kind='instruction'.\n\n"
    "Returns a list of results: id, scope, project_id, kind, title, snippet, "
    "score. Snippets are truncated — call memory_get with the id for the "
    "full content. An empty list is normal (nothing relevant stored yet), "
    "not an error.\n\n"
    "Parameters:\n"
    "- project_id (string, required): the project identifier\n"
    "- query (string, required): natural-language search text, 1-2000 characters\n"
    "- kind (string, optional): only memories of this kind, e.g. "
    "'decision', 'convention', 'gotcha', 'instruction'\n"
    "- scope (string, optional): 'project' or 'global'; omit to search both\n"
    "- user_id (string, optional): only memories authored by this user; "
    "this filters by author, it is not your identity\n"
    "- limit (integer, optional): maximum results; the server applies a "
    "default and a cap"
)

MEMORY_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string"},
        "query": {"type": "string", "minLength": 1, "maxLength": 2000},
        "kind": {"type": "string"},
        "scope": {"type": "string", "enum": ["project", "global"]},
        "user_id": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1},
    },
    "required": ["project_id", "query"],
}

MEMORY_UPDATE_DESCRIPTION = (
    "Refine an existing memory in place. Use this instead of memory_save "
    "when a memory you found via memory_search or memory_get is outdated or "
    "incomplete: update it rather than saving a duplicate.\n\n"
    "Send only the fields you want to change; at least one of title, "
    "content, tags, metadata is required. tags and metadata REPLACE the "
    "stored value (they are not merged): call memory_get first and send the "
    "full new value; an empty list or object clears the field. Only a "
    "content change re-embeds the memory. kind, scope, project_id, the "
    "author and timestamps cannot be changed: to change them, save a new "
    "memory and delete the old one.\n\n"
    "Returns the memory id. Unknown id: not_found.\n\n"
    "Parameters:\n"
    '- scope (required): "project" or "global" — the memory\'s scope\n'
    '- project_id (required): the project the memory belongs to ("_"\n'
    "  for global)\n"
    "- id (required): the memory ID returned by memory_save or memory_search\n"
    "- title (optional): new non-empty title\n"
    "- content (optional): new non-empty content\n"
    "- tags (optional): list of strings; replaces existing tags\n"
    "- metadata (optional): object; replaces existing metadata"
)

MEMORY_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["project", "global"]},
        "project_id": {"type": "string"},
        "id": {"type": "string"},
        "title": {"type": "string", "minLength": 1},
        "content": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "metadata": {"type": "object"},
    },
    "required": ["scope", "project_id", "id"],
    # Advisory only: the router remains the single validator.
    "anyOf": [
        {"required": ["title"]},
        {"required": ["content"]},
        {"required": ["tags"]},
        {"required": ["metadata"]},
    ],
}

MEMORY_DELETE_DESCRIPTION = (
    "Permanently delete a memory. This cannot be undone. Call it only when a "
    "memory is wrong or obsolete; to correct or refine a memory, prefer "
    "memory_update.\n\n"
    "Idempotent: deleting an id that does not exist (or was already deleted) "
    "still returns ok, so a retry is safe.\n\n"
    'Returns {"ok": true}.\n\n'
    "Parameters:\n"
    '- scope (required): "project" or "global" — the memory\'s scope\n'
    '- project_id (required): the project the memory belongs to ("_"\n'
    "  for global)\n"
    "- id (required): the memory ID returned by memory_save or memory_search"
)

MEMORY_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["project", "global"]},
        "project_id": {"type": "string"},
        "id": {"type": "string"},
    },
    "required": ["scope", "project_id", "id"],
}


class RequestContextMiddleware:
    """ASGI middleware that binds request-scoped fields into the structlog context.

    On every HTTP request it generates a ``request_id``, extracts
    ``trace_id``/``span_id`` from the active OTEL context (empty strings in
    no-op mode), and binds all three via :func:`bind_request_context`. After
    the downstream app finishes — success or exception — the context is cleared
    so no leakage across requests.
    """

    def __init__(
        self,
        app: ASGIApp,
        request_id_factory: Callable[[], str] | None = None,
        trace_context_provider: Callable[[], tuple[str, str]] | None = None,
    ) -> None:
        self._app = app
        self._request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        self._trace_context_provider = trace_context_provider or get_trace_context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = self._request_id_factory()
        trace_id, span_id = self._trace_context_provider()
        bind_request_context(request_id=request_id, trace_id=trace_id, span_id=span_id)

        status_code = 500
        start = time.perf_counter()

        async def _send_with_status_capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, _send_with_status_capture)
            _log.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        finally:
            unbind_request_context()


@dataclass
class _McpRuntime:
    """Mutable holder for the store-bound tool router.

    The router cannot be composed in :func:`create_app`: it needs the store
    *instance*, which only exists once the store's pool context is entered —
    and that happens in the lifespan. The MCP server's handlers (fixed at
    construction) read the router from this holder at call time.
    """

    router: ToolRouter | None = None


def _build_store(
    settings: Settings,
) -> AbstractAsyncContextManager[AsyncPostgresStore, bool | None]:
    """Build the AsyncPostgresStore wired to the stub embedder through ``guarded_embed``
    (ADR-0008, LLD §3.4).

    The vector dim is ``settings.embeddings.dim``, the same value ``ensure_schema``
    receives, and is fail-fast checked against the provider before the index
    config is built (LLD §LLD-e1-embedder). ``from_conn_string`` returns an
    async context manager: the connection pool and table setup are deferred
    to the app lifespan, so an unreachable DSN does not break construction.
    """
    from langgraph.store.postgres import AsyncPostgresStore
    from langgraph.store.postgres.base import PostgresIndexConfig

    embeddings = settings.embeddings
    # TODO(REC-16): select the provider with build_provider(embeddings).
    if embeddings.provider != "stub":
        _log.warning(
            "embeddings_provider_not_wired",
            provider=embeddings.provider,
            hint="this build embeds with the stub provider",
        )
    stub = StubEmbeddingsProvider(dim=embeddings.dim)
    # TODO(#91): this check is vacuous — the stub's dim comes from the same
    # setting the check compares against; the real mismatch (configured dim vs
    # the existing vector(N) column) still fails late, at the first write.
    # Deferred: catching it at startup needs schema introspection (Story 6.4).
    validate_dim(stub, embeddings.dim)

    return AsyncPostgresStore.from_conn_string(
        settings.database_url,
        index=PostgresIndexConfig(dims=embeddings.dim, embed=guarded_embed(stub)),
    )


def _build_mcp_server(auth_config: AuthConfig, runtime: _McpRuntime) -> Server:
    """Build the lowlevel MCP server (2026-07-28 protocol revision).

    ``Server`` takes the tool surface as ``on_list_tools``/``on_call_tool``
    callbacks in its constructor. The call-tool handler resolves ``user_id``
    from the Authorization header on the transport-stamped request
    (``ServerRequestContext.request`` — the SDK attaches the Starlette
    Request to the message metadata at the ASGI boundary, so handlers see
    HTTP headers without middleware hacks). The SDK does no input
    pre-validation in the dispatcher, so the router stays the single
    validator (AC1) and exactly one ``mcp_call`` event is emitted per call
    (AC3/ADR-0011); the structured validation errors (AC1/AC4) are the
    router's ``{error, hint}`` payloads.
    """

    async def _call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        request = ctx.request
        authorization = request.headers.get("authorization") if request is not None else None
        try:
            user_id = authenticate(auth_config, authorization)
        except UnauthenticatedError as exc:
            # LLD §LLD-e1-behavioural-auth-failure: auth failures are logged
            # at the transport and returned as structured tool results.
            _log.warning("auth_reject", hint=exc.hint)
            payload: dict[str, Any] = {"error": exc.error, "hint": exc.hint}
        else:
            # ASGI guarantees lifespan startup completes before any request,
            # so the lifespan has filled the router by the time a call lands.
            assert runtime.router is not None
            payload = await runtime.router.handle_tool_call(
                params.name, params.arguments or {}, user_id
            )
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])

    return Server("recall", on_list_tools=_list_tools, on_call_tool=_call_tool)


async def _list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    """Declare the MCP tool surface (LLD §LLD-e1-mcp-tool-declarations; Story 4.2)."""
    return ListToolsResult(
        tools=[
            Tool(
                name="memory_save",
                description=MEMORY_SAVE_DESCRIPTION,
                input_schema=MEMORY_SAVE_SCHEMA,
            ),
            Tool(
                name="memory_get",
                description=MEMORY_GET_DESCRIPTION,
                input_schema=MEMORY_GET_SCHEMA,
            ),
            Tool(
                name="memory_search",
                description=MEMORY_SEARCH_DESCRIPTION,
                input_schema=MEMORY_SEARCH_SCHEMA,
            ),
            Tool(
                name="memory_update",
                description=MEMORY_UPDATE_DESCRIPTION,
                input_schema=MEMORY_UPDATE_SCHEMA,
            ),
            Tool(
                name="memory_delete",
                description=MEMORY_DELETE_DESCRIPTION,
                input_schema=MEMORY_DELETE_SCHEMA,
            ),
        ]
    )


class StoreUnavailableError(RuntimeError):
    """The store could not be opened at startup. Carries no part of ``DATABASE_URL``."""


# Justification: the server logs a lifespan failure with its traceback, so the driver's
# message must be replaced before it gets there (LLD I2).
@asynccontextmanager
async def _opened(
    store: AbstractAsyncContextManager[AsyncPostgresStore, bool | None],
) -> AsyncIterator[AsyncPostgresStore]:
    """Enter ``store``, replacing a failure to open it with ``StoreUnavailableError``."""
    entered = False
    try:
        async with store as instance:
            entered = True
            yield instance
    except Exception as exc:
        if entered:
            raise
        raise StoreUnavailableError(describe_db_error(exc)) from None


def _build_lifespan(
    store: AbstractAsyncContextManager[AsyncPostgresStore, bool | None],
    auth_config: AuthConfig,
    mcp_runtime: _McpRuntime,
    mcp_server: Server,
    search_config: SearchConfig,
) -> Callable[[Starlette], AbstractAsyncContextManager[None, bool | None]]:
    """Lifespan: open the store pool, wire the router, run the dispatcher.

    The MCP dispatcher task group must run for the whole app lifetime — even
    in stateless mode every request runs through it (the SDK raises if it is
    not entered). It is composed here because the tool router needs the store
    *instance*, which only exists once the pool context is entered; the MCP
    server's handlers read it from ``mcp_runtime``. The store is entered
    first so the pool exists before any request can issue a call; both are
    closed (in reverse order) on shutdown.
    """

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with _opened(store) as store_instance:
            mcp_runtime.router = ToolRouter(
                MemoryService(StorageAdapter(store_instance), search_config)
            )
            async with mcp_server.session_manager.run():
                yield

    return lifespan


def create_app(settings: Settings) -> Starlette:
    """Create the ASGI application.

    Mounts:
      * ``/healthz`` — liveness probe
      * ``/readyz``  — readiness probe, runs ``SELECT 1`` against the database
      * ``/mcp``     — MCP Streamable HTTP endpoint (ADR-0006): memory_save
        and memory_get behind bearer-token auth (ADR-0007), served by the
        SDK's Streamable HTTP ASGI app

    Installs :class:`RequestContextMiddleware` so every log line emitted while
    handling a request carries ``request_id``/``trace_id``/``span_id``.

    The MCP tool surface is composed once at startup: auth config from
    ``settings.auth_file``, a lazy :class:`AsyncPostgresStore` over
    ``settings.database_url`` with the stub embedder, the
    MemoryService → StorageAdapter → store chain behind a :class:`ToolRouter`,
    and the lowlevel MCP server. The store pool and the dispatcher task group
    run for the app's lifetime (see :func:`_build_lifespan`).

    ``settings.database_url`` is stashed on ``app.state.conn_string`` so the health
    handlers can reach it without module-level state.
    """
    auth_config = load_auth_config(settings.auth_file)
    store = _build_store(settings)
    mcp_runtime = _McpRuntime()
    mcp_server = _build_mcp_server(auth_config, mcp_runtime)

    # Stateless Streamable HTTP (design decision, PR #117): the 2026-07-28
    # MCP protocol removed sessions and the initialize handshake from
    # Streamable HTTP entirely — no MCP-Session-Id, no SSE stream, inline
    # JSON responses via json_response=True; every tool call completes in
    # one round trip. The SDK sub-app routes /mcp itself, so it mounts at
    # the root. host="0.0.0.0" mirrors cli's bind default and keeps the
    # SDK's DNS-rebinding auto-protection off (it only engages for localhost
    # binds; a public deploy needs its configured hostname — serve epic).
    mcp_app = mcp_server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",  # noqa: S104 — container deploys bind to all interfaces (cli.py convention)
    )

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Mount("/", mcp_app),
        ],
        middleware=[Middleware(RequestContextMiddleware)],
        lifespan=_build_lifespan(store, auth_config, mcp_runtime, mcp_server, settings.search),
    )
    app.state.conn_string = settings.database_url
    return app
