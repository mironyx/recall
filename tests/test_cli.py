"""Tests for CLI commands.

Verifies that CLI commands are wired and produce clean exits.
"""

from __future__ import annotations

import os
import subprocess
import sys


class TestCLIStubs:
    """CLI commands are reachable and produce clean output."""

    def test_serve_dry_run_exits_cleanly(self) -> None:
        """recall serve --dry-run wires logging/telemetry/app and exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "recall.cli", "serve", "--dry-run"],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_db_migrate_without_database_url_exits_one(self) -> None:
        """recall db migrate without DATABASE_URL exits 1 with clean error."""
        result = subprocess.run(
            [sys.executable, "-m", "recall.cli", "db", "migrate"],
            capture_output=True,
            timeout=10,
            env={"PATH": os.environ.get("PATH", "")},
        )
        assert result.returncode == 1
        assert b"Traceback" not in result.stderr
        assert b"DATABASE_URL" in result.stderr
