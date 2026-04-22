"""Tests for top-level CLI behaviour.

Originally added in #73 (E0.1 scaffolding) to exercise stub commands. Once #76
wired ``recall serve`` and ``recall db migrate`` to the migration runner these
tests now verify that each command fails cleanly (exit 1, no traceback) when
``DATABASE_URL`` is missing — the migration tests in ``test_migrations.py``
cover the happy path with a real Postgres.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _run_without_db(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "recall.cli", *args],
        capture_output=True,
        timeout=10,
        env={"PATH": os.environ.get("PATH", "")},
    )


class TestCLIWithoutDatabaseURL:
    """Both commands exit cleanly (code 1, no traceback) without DATABASE_URL."""

    def test_serve_exits_one(self) -> None:
        result = _run_without_db(["serve"])
        assert result.returncode == 1
        assert b"Traceback" not in result.stderr
        assert b"DATABASE_URL" in result.stderr

    def test_db_migrate_exits_one(self) -> None:
        result = _run_without_db(["db", "migrate"])
        assert result.returncode == 1
        assert b"Traceback" not in result.stderr
        assert b"DATABASE_URL" in result.stderr
