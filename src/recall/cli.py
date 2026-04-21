"""Recall CLI entry point."""

from __future__ import annotations

import argparse
import sys


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the Recall MCP server (stub)."""
    del args  # unused


def _cmd_db_migrate(args: argparse.Namespace) -> None:
    """Run pending database migrations (stub)."""
    del args  # unused


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Build the CLI argument parser. Returns (root_parser, db_parser)."""
    parser = argparse.ArgumentParser(prog="recall", description="Recall MCP memory server")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Start the MCP server")

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
