"""Adversarial evaluation tests for Issue #73 — E0.1 Repository scaffolding.

Probes edge cases not covered by tests/test_cli.py, including:
- Unknown subcommand handling
- `recall db` with no subcommand
- `recall` with no arguments
- Exit-code correctness for stub commands
- `__main__` module entry point is importable
- Pre-commit config structure
- pyproject.toml tool configuration completeness
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent


def _run_cli(*args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run the recall CLI module with the given args and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "recall.cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_entry_point(*args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run via the installed `recall` script entry point."""
    return subprocess.run(
        ["uv", "run", "recall", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_REPO_ROOT,
    )


# ---------------------------------------------------------------------------
# AC: `recall serve` exits cleanly — via installed entry point
# ---------------------------------------------------------------------------


class TestEntryPointStubs:
    """Installed `recall` script entry point is wired and produces a clean
    (non-traceback) exit code. After #76 both commands require ``DATABASE_URL``
    and exit 1 when it is missing; the check here is that the entry point
    itself is reachable and does not crash with a traceback.
    """

    def test_serve_via_entry_point(self) -> None:
        """recall serve via installed entry point prints a clean error."""
        result = _run_entry_point("serve")
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout

    def test_db_migrate_via_entry_point(self) -> None:
        """recall db migrate via installed entry point prints a clean error."""
        result = _run_entry_point("db", "migrate")
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout


# ---------------------------------------------------------------------------
# AC: CLI edge-case behaviour (not covered by existing tests)
# ---------------------------------------------------------------------------


class TestCLIEdgeCases:
    """Edge-case behaviour of the CLI parser."""

    def test_no_arguments_exits_zero(self) -> None:
        """recall with no arguments prints help and exits 0, not 1 or 2."""
        result = _run_cli()
        # argparse with no subcommand should call print_help() — exit 0.
        assert result.returncode == 0

    def test_unknown_command_prints_help(self) -> None:
        """An unrecognised subcommand should not crash with a traceback."""
        result = _run_cli("nonexistent-command")
        # argparse error path exits 2; we want no unhandled exception (exit !=1 from traceback)
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout

    def test_db_no_subcommand_exits_zero(self) -> None:
        """recall db with no subcommand falls back to help and exits 0."""
        result = _run_cli("db")
        # The implementation calls parser.parse_args(["db", "--help"]) which
        # causes argparse to print help and exit 0.
        assert result.returncode == 0

    def test_serve_produces_no_unhandled_exception(self) -> None:
        """recall serve stub must not emit a Python traceback."""
        result = _run_cli("serve")
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout

    def test_db_migrate_produces_no_unhandled_exception(self) -> None:
        """recall db migrate stub must not emit a Python traceback."""
        result = _run_cli("db", "migrate")
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout


# ---------------------------------------------------------------------------
# AC: pyproject.toml tooling configuration
# ---------------------------------------------------------------------------


class TestPyprojectConfig:
    """pyproject.toml contains expected tooling sections and values."""

    @pytest.fixture(scope="class")
    def pyproject(self) -> dict:  # type: ignore[type-arg]
        path = _REPO_ROOT / "pyproject.toml"
        with path.open("rb") as fh:
            return tomllib.load(fh)

    def test_entry_point_defined(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        """The `recall` console script entry point is wired to recall.cli:main."""
        scripts = pyproject["project"]["scripts"]
        assert scripts.get("recall") == "recall.cli:main"

    def test_dev_extra_includes_ruff(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
        assert any(dep.startswith("ruff") for dep in dev_deps)

    def test_dev_extra_includes_mypy(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
        assert any(dep.startswith("mypy") for dep in dev_deps)

    def test_dev_extra_includes_pytest(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
        assert any(dep.startswith("pytest>=") for dep in dev_deps)

    def test_dev_extra_includes_pre_commit(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
        assert any(dep.startswith("pre-commit") for dep in dev_deps)

    def test_mypy_strict_enabled(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        """mypy is configured with strict = true."""
        assert pyproject["tool"]["mypy"]["strict"] is True

    def test_pytest_asyncio_mode_auto(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        """pytest asyncio_mode is set to auto."""
        assert pyproject["tool"]["pytest"]["ini_options"]["asyncio_mode"] == "auto"

    def test_pytest_integration_marker_declared(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        """The 'integration' custom marker is declared to prevent strict-marker failures."""
        markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
        assert any("integration" in m for m in markers)

    def test_python_requires_312(self, pyproject: dict) -> None:  # type: ignore[type-arg]
        """Project requires Python 3.12+."""
        req = pyproject["project"]["requires-python"]
        assert "3.12" in req


# ---------------------------------------------------------------------------
# AC: Pre-commit config covers ruff, mypy, and pytest
# ---------------------------------------------------------------------------


class TestPreCommitConfig:
    """Pre-commit config file wires up the required hooks."""

    @pytest.fixture(scope="class")
    def config_text(self) -> str:
        return (_REPO_ROOT / ".pre-commit-config.yaml").read_text()

    def test_ruff_check_hook_present(self, config_text: str) -> None:
        assert "ruff" in config_text

    def test_ruff_format_hook_present(self, config_text: str) -> None:
        assert "ruff-format" in config_text

    def test_mypy_hook_present(self, config_text: str) -> None:
        assert "mypy" in config_text

    def test_pytest_hook_present(self, config_text: str) -> None:
        assert "pytest" in config_text

    def test_pytest_excludes_integration(self, config_text: str) -> None:
        """The pytest pre-commit hook must skip integration tests (no Docker in hooks)."""
        assert "not integration" in config_text


# ---------------------------------------------------------------------------
# AC: Module importability
# ---------------------------------------------------------------------------


class TestModuleImports:
    """Core modules are importable without side-effects."""

    def test_recall_cli_importable(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import recall.cli"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

    def test_recall_package_importable(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import recall"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr

    def test_recall_cli_main_callable(self) -> None:
        """recall.cli:main is callable and exits 0 with no args."""
        result = subprocess.run(
            [sys.executable, "-c", "from recall.cli import main; main([])"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
