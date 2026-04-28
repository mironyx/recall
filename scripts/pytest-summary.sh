#!/usr/bin/env bash
# Run pytest on the given file(s) and emit a compact summary.
# Usage: bash scripts/pytest-summary.sh <test-file> [pytest-args...]
# Exit code matches pytest's exit code.
set -uo pipefail

tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

uv run pytest "$@" > "$tmpfile" 2>&1
pytest_exit=$?

uv run python scripts/parse-pytest-output.py < "$tmpfile"
exit $pytest_exit
