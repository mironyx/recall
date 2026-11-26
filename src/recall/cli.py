"""Recall CLI entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from recall.settings import Settings


def _cmd_serve(args: argparse.Namespace, env: Mapping[str, str]) -> None:
    """Start the Recall MCP server.

    Wires logging → telemetry → settings → optional auto-migrate → ASGI app → uvicorn.
    """
    import psycopg
    import structlog

    from recall.db.schema import describe_db_error
    from recall.logging import configure_logging
    from recall.server import create_app
    from recall.settings import load_settings
    from recall.telemetry import configure_telemetry

    configure_logging(args.log_level or "INFO")
    configure_telemetry(env)
    settings = _apply_flags(_load_or_exit(load_settings, env), args)
    configure_logging(settings.log_level)

    log = structlog.get_logger(__name__)
    if settings.migrate_on_startup:
        _migrate_or_exit(settings.database_url, settings.embeddings.dim)

    try:
        app = create_app(settings)
    except Exception as exc:
        detail = describe_db_error(exc) if isinstance(exc, psycopg.Error) else str(exc)
        log.error("startup_failed", error_type=type(exc).__name__, error=detail)
        sys.exit(1)

    if args.dry_run:
        return

    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)


# Justification: shared by `serve` and `db migrate` so both report settings errors alike.
def _load_or_exit[T](load: Callable[[Mapping[str, str]], T], env: Mapping[str, str]) -> T:
    """Run a settings loader; on ``SettingsError`` print it and exit 1."""
    from recall.settings import SettingsError

    try:
        return load(env)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


# Justification: flag precedence is a pure step, separate from startup wiring.
def _apply_flags(settings: Settings, args: argparse.Namespace) -> Settings:
    """Override settings with the flags actually given on the command line."""
    given = {
        name: value
        for name in ("host", "port", "log_level")
        if (value := getattr(args, name)) is not None
    }
    return replace(settings, **given)


# Justification: isolates the auto-migrate failure path (complexity gate).
def _migrate_or_exit(database_url: str, dims: int) -> None:
    """Auto-migrate for ``serve``; log and exit 1 on failure."""
    import asyncio

    import structlog

    from recall.db.schema import describe_db_error, ensure_schema

    try:
        asyncio.run(ensure_schema(database_url, dims))
    except Exception as exc:
        structlog.get_logger(__name__).error("schema_setup_failed", error=describe_db_error(exc))
        sys.exit(1)


def _cmd_db_migrate(env: Mapping[str, str]) -> None:
    """Run idempotent schema setup and report."""
    from recall.settings import load_db_settings

    db = _load_or_exit(load_db_settings, env)

    import asyncio

    from recall.db.schema import describe_db_error, ensure_schema

    try:
        asyncio.run(ensure_schema(db.database_url, db.embeddings_dim))
    except Exception as exc:
        print(f"error: schema setup failed: {describe_db_error(exc)}", file=sys.stderr)
        sys.exit(1)
    print("Schema is up to date")


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Build the CLI argument parser. Returns (root_parser, db_parser)."""
    parser = argparse.ArgumentParser(prog="recall", description="Recall MCP memory server")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--host", help="bind host (default: RECALL_HOST or 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, help="bind port (default: RECALL_PORT or 8080)")
    serve_parser.add_argument("--log-level", help="log level (default: LOG_LEVEL or INFO)")
    serve_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="configure logging/telemetry and build the app, then exit (used by tests)",
    )

    db_parser = sub.add_parser("db", help="Database operations")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("migrate", help="Run pending migrations")

    return parser, db_parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser, db_parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    env = os.environ  # the one read of the process environment (LLD I1)

    if args.command == "serve":
        _cmd_serve(args, env)
    elif args.command == "db":
        if getattr(args, "db_command", None) == "migrate":
            _cmd_db_migrate(env)
        else:
            db_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
