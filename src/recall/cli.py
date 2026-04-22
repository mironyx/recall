"""Recall CLI entry point."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 — container deploys bind to all interfaces
DEFAULT_PORT = 8080


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the Recall MCP server.

    Wires logging → telemetry → optional auto-migrate → ASGI app → uvicorn.
    """
    import asyncio

    import structlog

    from recall.logging import configure_logging
    from recall.server import create_app
    from recall.telemetry import configure_telemetry

    configure_logging(args.log_level)
    configure_telemetry()

    log = structlog.get_logger(__name__)
    conn_string = os.environ.get("DATABASE_URL", "")
    if not conn_string:
        log.warning(
            "database_url_unset",
            message="DATABASE_URL is not set; /readyz will return 503 until it is.",
        )
    elif _migrate_on_startup():
        from recall.db.schema import ensure_schema

        try:
            asyncio.run(ensure_schema(conn_string))
        except Exception:
            log.exception("schema_setup_failed")
            sys.exit(1)

    app = create_app(conn_string)

    if getattr(args, "dry_run", False):
        return

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


_FALSY_ENV_VALUES = frozenset({"0", "false", "no", "off", ""})


def _migrate_on_startup() -> bool:
    """Whether ``recall serve`` should run ``ensure_schema`` on startup."""
    value = os.environ.get("RECALL_DB_MIGRATE_ON_STARTUP", "true").strip().lower()
    return value not in _FALSY_ENV_VALUES


def _require_database_url() -> str:
    """Read ``DATABASE_URL`` from env or exit non-zero."""
    conn_string = os.environ.get("DATABASE_URL")
    if not conn_string:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return conn_string


def _cmd_db_migrate(_args: argparse.Namespace) -> None:
    """Run idempotent schema setup and report."""
    conn_string = _require_database_url()

    import asyncio

    from recall.db.schema import ensure_schema

    try:
        asyncio.run(ensure_schema(conn_string))
    except Exception as exc:
        print(f"error: schema setup failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Schema is up to date")


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Build the CLI argument parser. Returns (root_parser, db_parser)."""
    parser = argparse.ArgumentParser(prog="recall", description="Recall MCP memory server")
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument(
        "--host",
        default=os.environ.get("RECALL_HOST", DEFAULT_HOST),
        help="bind host (default: RECALL_HOST or 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("RECALL_PORT", DEFAULT_PORT)),
        help="bind port (default: RECALL_PORT or 8080)",
    )
    serve_parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="log level (default: LOG_LEVEL or INFO)",
    )
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

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "db":
        if getattr(args, "db_command", None) == "migrate":
            _cmd_db_migrate(args)
        else:
            db_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
