"""Recall CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_FALSY_ENV_VALUES = frozenset({"0", "false", "no", "off", ""})


def _migrate_on_startup() -> bool:
    """Whether ``recall serve`` should run pending migrations on startup.

    Default is on; standard falsy strings disable it.
    """
    value = os.environ.get("RECALL_DB_MIGRATE_ON_STARTUP", "true").strip().lower()
    return value not in _FALSY_ENV_VALUES


def _require_database_url() -> str:
    """Read ``DATABASE_URL`` from the environment or print and exit non-zero."""
    conn_string = os.environ.get("DATABASE_URL")
    if not conn_string:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)
    return conn_string


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the Recall MCP server.

    Phase 0: this is a stub. It still honours the auto-migrate-on-startup
    contract — if ``RECALL_DB_MIGRATE_ON_STARTUP`` is unset or truthy, pending
    migrations run before the (eventual) server boots. A migration failure
    aborts startup with exit code 1.
    """
    del args
    from recall.db.migrations import apply_pending

    if _migrate_on_startup():
        conn_string = _require_database_url()
        try:
            asyncio.run(apply_pending(conn_string))
        except Exception as exc:
            print(f"error: migration failed: {exc}", file=sys.stderr)
            return 1
    # Server itself is wired in a later phase.
    return 0


def _cmd_db_migrate(args: argparse.Namespace) -> int:
    """Run pending database migrations and report what was applied."""
    del args
    from recall.db.migrations import apply_pending

    conn_string = _require_database_url()
    try:
        applied = asyncio.run(apply_pending(conn_string))
    except Exception as exc:
        print(f"error: migration failed: {exc}", file=sys.stderr)
        return 1

    if applied:
        print(f"Applied {len(applied)} migrations: {', '.join(applied)}")
    else:
        print("No pending migrations")
    return 0


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Build the CLI argument parser. Returns (root_parser, db_parser)."""
    parser = argparse.ArgumentParser(prog="recall", description="Recall MCP memory server")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Start the MCP server")

    db_parser = sub.add_parser("db", help="Database operations")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("migrate", help="Run pending migrations")

    return parser, db_parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser, db_parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "db":
        if getattr(args, "db_command", None) == "migrate":
            return _cmd_db_migrate(args)
        db_parser.print_help()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
