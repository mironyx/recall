"""Tests for REC-15 startup failures (LLD §LLD-e4-settings).

An embeddings provider that is not wired stops startup before any migration, and every
startup failure logs where it happened without revealing any part of ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import os
import traceback
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from recall.cli import main
from recall.errors import StartupError
from recall.server import create_app
from recall.settings import load_settings
from tests.test_settings import (
    _DB_SENTINEL,
    _KEY_SENTINEL,
    _auth_file,
    _openai_env,
    _run_cli,
    _stub_env,
)

_EMPTY_AUTH = Path(__file__).parent / "fixtures" / "empty-auth.json"

# ---------------------------------------------------------------------------
# Unwired providers fail startup (REC-15 review)
# ---------------------------------------------------------------------------

_UNWIRED = [("openai", "REC-16"), ("sentence-transformers", "REC-17")]


class TestUnwiredProvider:
    @pytest.mark.parametrize(("provider", "issue"), _UNWIRED)
    def test_create_app_refuses_naming_support_and_issue(self, provider: str, issue: str) -> None:
        settings = load_settings(
            _openai_env(EMBEDDINGS_PROVIDER=provider, RECALL_AUTH_FILE=str(_EMPTY_AUTH))
        )

        with pytest.raises(StartupError) as excinfo:
            create_app(settings)

        message = str(excinfo.value)
        for expected in ("EMBEDDINGS_PROVIDER", provider, "stub", issue):
            assert expected in message
        assert _KEY_SENTINEL not in message
        assert "sentinel" not in message

    @pytest.mark.parametrize(("provider", "issue"), _UNWIRED)
    def test_serve_exits_one_before_migrating(
        self, provider: str, issue: str, tmp_path: Path
    ) -> None:
        """Auto-migrate is on and the database unreachable: a migration attempt would show."""
        env = _openai_env(EMBEDDINGS_PROVIDER=provider, DATABASE_URL=_DB_SENTINEL)

        result = _run_cli(["serve"], env | {"RECALL_AUTH_FILE": str(_EMPTY_AUTH)}, tmp_path)

        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "startup_failed" in output
        assert "EMBEDDINGS_PROVIDER" in output
        assert issue in output
        assert "schema_setup_failed" not in output
        assert "sentinel" not in output


# ---------------------------------------------------------------------------
# Startup failures keep their location and no exception text (REC-15 review, I2)
# ---------------------------------------------------------------------------

_SECRET = "sentinel-db-password"


def _leaky_error() -> RuntimeError:
    """An error whose message, cause and local variable all carry the URL."""
    url = _DB_SENTINEL
    error = RuntimeError(f"bad url {url}")
    error.__cause__ = ValueError(url)
    return error


def _explode(*args: object, **kwargs: object) -> Any:
    raise _leaky_error()


async def _explode_async(*args: object, **kwargs: object) -> Any:
    raise _leaky_error()


class _ExplodingStore:
    async def __aenter__(self) -> None:
        raise _leaky_error()

    async def __aexit__(self, *exc: object) -> None:
        return None


def _events(logs: list[MutableMapping[str, Any]], name: str) -> list[MutableMapping[str, Any]]:
    return [entry for entry in logs if entry["event"] == name]


class _CliFailure(NamedTuple):
    target: str
    event: str
    migrate: bool


@pytest.fixture
def failing_serve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reset_logging: None,
    tmp_path: Path,
) -> Callable[[_CliFailure], tuple[int, str]]:
    """Run ``serve`` with one startup step raising; return the exit code and all output."""

    def run(case: _CliFailure) -> tuple[int, str]:
        monkeypatch.setattr(case.target, _explode_async if case.migrate else _explode)
        if case.migrate:
            monkeypatch.setattr("recall.server.create_app", lambda settings: None)
        env = _stub_env(
            DATABASE_URL=_DB_SENTINEL,
            RECALL_AUTH_FILE=_auth_file(tmp_path),
            RECALL_DB_MIGRATE_ON_STARTUP=str(case.migrate).lower(),
        )
        monkeypatch.setattr(os, "environ", env)
        with pytest.raises(SystemExit) as excinfo:
            main(["serve", "--dry-run"])
        output = capsys.readouterr()
        return int(str(excinfo.value.code)), output.out + output.err

    return run


class TestStartupFailureLocation:
    async def test_store_open_failure_logs_frames_without_messages(
        self,
        captured_logs: list[MutableMapping[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "langgraph.store.postgres.AsyncPostgresStore.from_conn_string",
            lambda *args, **kwargs: _ExplodingStore(),
        )
        app = create_app(load_settings(_stub_env(RECALL_AUTH_FILE=str(_EMPTY_AUTH))))

        with pytest.raises(Exception) as excinfo:
            async with app.router.lifespan_context(app):
                pass

        (entry,) = _events(captured_logs, "store_unavailable")
        assert entry["error_type"] == "RuntimeError"
        assert "__aenter__" in "".join(entry["frames"])
        printed = str(captured_logs) + "".join(traceback.format_exception(excinfo.value))
        assert _SECRET not in printed

    @pytest.mark.parametrize(
        "case",
        [
            _CliFailure("recall.db.schema.ensure_schema", "schema_setup_failed", True),
            _CliFailure("recall.server.create_app", "startup_failed", False),
        ],
        ids=lambda case: case.event,
    )
    def test_cli_failure_logs_frames_without_messages(
        self, case: _CliFailure, failing_serve: Callable[[_CliFailure], tuple[int, str]]
    ) -> None:
        code, output = failing_serve(case)

        (line,) = [text for text in output.splitlines() if case.event in text]
        entry = json.loads(line)
        assert code == 1
        assert entry["error_type"] == "RuntimeError"
        assert "_explode" in "".join(entry["frames"])
        assert _SECRET not in output

    @pytest.mark.parametrize("content", [None, "not json"], ids=["absent", "malformed"])
    def test_bad_auth_file_is_explained(self, content: str | None, tmp_path: Path) -> None:
        path = tmp_path / "auth.json"
        if content is not None:
            path.write_text(content)
        env = _stub_env(RECALL_AUTH_FILE=str(path), RECALL_DB_MIGRATE_ON_STARTUP="false")

        result = _run_cli(["serve", "--dry-run"], env, tmp_path)

        assert result.returncode == 1
        assert "RECALL_AUTH_FILE" in result.stdout

    def test_database_url_given_as_auth_file_is_not_echoed(self, tmp_path: Path) -> None:
        env = _stub_env(
            DATABASE_URL=_DB_SENTINEL,
            RECALL_AUTH_FILE=_DB_SENTINEL,
            RECALL_DB_MIGRATE_ON_STARTUP="false",
        )

        result = _run_cli(["serve", "--dry-run"], env, tmp_path)

        assert result.returncode == 1
        assert "startup_failed" in result.stdout
        assert _SECRET not in result.stdout + result.stderr
