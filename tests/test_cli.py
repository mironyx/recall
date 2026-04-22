"""Tests for CLI stubs — Issue #73 (E0.1: Repository scaffolding and tooling).

Verifies that the two CLI stub commands exit cleanly with code 0.
"""

from __future__ import annotations

import subprocess
import sys


class TestCLIStubs:
    """CLI stub commands exit cleanly."""

    def test_serve_exits_cleanly(self) -> None:
        """recall serve --dry-run wires logging/telemetry/app and exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "recall.cli", "serve", "--dry-run"],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_db_migrate_exits_cleanly(self) -> None:
        """recall db migrate stub exits with code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "recall.cli", "db", "migrate"],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0
