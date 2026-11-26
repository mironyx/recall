"""Tests for REC-15 — E4.0: Settings loader and fail-fast startup.

Contract:

- ``docs/design/v2/lld-e4-deployment.md`` §4.1 (anchor LLD-e4-settings): required
  variables table, invariants I1-I3, types and signatures, CLI decomposition.
- ``docs/requirements/v2-requirements.md`` Stories 6.1 and 6.4.

The loaders are pure: the environment is passed as a plain dict. Subprocess tests
pass an explicit minimal environment, never the developer's own.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import Any

import psycopg
import pytest
import uvicorn

from recall.cli import main
from recall.config import SearchConfig
from recall.db.schema import ensure_schema
from recall.errors import StartupError
from recall.server import create_app
from recall.settings import (
    SETTINGS_VARIABLES,
    DbSettings,
    EmbeddingsSettings,
    Settings,
    SettingsError,
    load_db_settings,
    load_settings,
)
from recall.telemetry import configure_telemetry

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Well-formed but unreachable: port 1 refuses connections.
_DB_URL = "postgresql://nouser:nopass@127.0.0.1:1/nodb"
_DB_SENTINEL = "postgresql://sentineluser:sentinel-db-password@127.0.0.1:1/sentineldb"
_KEY_SENTINEL = "sk-sentinel-api-key-value"

_ALWAYS_REQUIRED = ("DATABASE_URL", "RECALL_AUTH_FILE", "EMBEDDINGS_PROVIDER", "EMBEDDINGS_DIM")
_OPENAI_REQUIRED = ("EMBEDDINGS_MODEL", "EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY")

_INVALID_VALUES = [
    ("EMBEDDINGS_PROVIDER", "cohere"),
    ("EMBEDDINGS_DIM", "abc"),
    ("EMBEDDINGS_DIM", "1.5"),
    ("EMBEDDINGS_DIM", "0"),
    ("EMBEDDINGS_DIM", "-8"),
    ("RECALL_PORT", "abc"),
    ("RECALL_PORT", "80.5"),
    ("EMBEDDINGS_TIMEOUT_SECONDS", "soon"),
    ("RECALL_PROJECT_BOOST", "0.5"),
    ("RECALL_PROJECT_BOOST", "high"),
    ("RECALL_DEFAULT_LIMIT", "ten"),
    ("RECALL_MAX_LIMIT", "many"),
    ("RECALL_SNIPPET_MAX_CHARS", "long"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_env(**overrides: str) -> dict[str, str]:
    """The smallest environment ``load_settings`` accepts (stub provider)."""
    env = {
        "DATABASE_URL": _DB_URL,
        "RECALL_AUTH_FILE": "/nonexistent/auth.json",
        "EMBEDDINGS_PROVIDER": "stub",
        "EMBEDDINGS_DIM": "8",
    }
    env.update(overrides)
    return env


def _openai_env(**overrides: str) -> dict[str, str]:
    """A complete ``openai`` provider environment."""
    env = _stub_env(
        EMBEDDINGS_PROVIDER="openai",
        EMBEDDINGS_MODEL="text-embedding-3-small",
        EMBEDDINGS_BASE_URL="https://embeddings.example.com/v1",
        EMBEDDINGS_API_KEY=_KEY_SENTINEL,
    )
    env.update(overrides)
    return env


def _without(env: Mapping[str, str], *names: str) -> dict[str, str]:
    return {key: value for key, value in env.items() if key not in names}


def _named(message: str) -> set[str]:
    """The settings variables a message mentions."""
    return {name for name in SETTINGS_VARIABLES if re.search(rf"\b{name}\b", message)}


def _settings_error(env: Mapping[str, str]) -> str:
    with pytest.raises(SettingsError) as excinfo:
        load_settings(env)
    return str(excinfo.value)


def _db_settings_error(env: Mapping[str, str]) -> str:
    with pytest.raises(SettingsError) as excinfo:
        load_db_settings(env)
    return str(excinfo.value)


def _auth_file(directory: Path) -> str:
    path = directory / "auth.json"
    path.write_text('{"test-token": {"user_id": "alice"}}')
    return str(path)


def _run_cli(args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``recall`` in a subprocess with exactly ``env`` (plus a minimal PATH)."""
    return subprocess.run(
        [sys.executable, "-m", "recall.cli", *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=cwd,
        env={"PATH": os.defpath, **env},
    )


def _assert_clean_failure(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 1, result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
    assert "error:" in result.stderr


class _RecordingEnv(Mapping[str, str]):
    """A mapping that records every key looked up."""

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


# ---------------------------------------------------------------------------
# SettingsError message shape (REC-15)
# ---------------------------------------------------------------------------


class TestSettingsError:
    def test_missing_only_message_lists_names(self) -> None:
        message = str(SettingsError(missing=["DATABASE_URL", "EMBEDDINGS_DIM"]))

        assert "missing required environment variables: DATABASE_URL, EMBEDDINGS_DIM" in message
        assert "invalid" not in message

    def test_invalid_only_message_lists_entries(self) -> None:
        message = str(
            SettingsError(invalid=["RECALL_PORT (not an integer)", "EMBEDDINGS_DIM (not positive)"])
        )

        assert "invalid: RECALL_PORT (not an integer), EMBEDDINGS_DIM (not positive)" in message
        assert "missing" not in message

    def test_message_carries_both_missing_and_invalid(self) -> None:
        message = str(
            SettingsError(missing=["DATABASE_URL"], invalid=["RECALL_PORT (not an integer)"])
        )

        assert "missing required environment variables: DATABASE_URL" in message
        assert "invalid: RECALL_PORT (not an integer)" in message


# ---------------------------------------------------------------------------
# load_settings (REC-15)
# ---------------------------------------------------------------------------


class TestLoadSettings:
    def test_empty_env_lists_every_always_required_variable(self) -> None:
        message = _settings_error({})

        assert "missing required environment variables" in message
        assert _named(message) == set(_ALWAYS_REQUIRED)

    @pytest.mark.parametrize("name", _ALWAYS_REQUIRED)
    def test_each_always_required_variable_is_reported_alone(self, name: str) -> None:
        message = _settings_error(_without(_stub_env(), name))

        assert "missing required environment variables" in message
        assert _named(message) == {name}

    @pytest.mark.parametrize("name", [*_ALWAYS_REQUIRED, *_OPENAI_REQUIRED])
    def test_empty_string_counts_as_unset_for_required_variables(self, name: str) -> None:
        message = _settings_error(_openai_env(**{name: ""}))

        assert "missing required environment variables" in message
        assert _named(message) == {name}

    def test_openai_requires_base_url_and_api_key(self) -> None:
        env = _without(_openai_env(), "EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY")

        message = _settings_error(env)

        assert "missing required environment variables" in message
        assert _named(message) == {"EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY"}

    def test_openai_requires_model(self) -> None:
        message = _settings_error(_without(_openai_env(), "EMBEDDINGS_MODEL"))

        assert _named(message) == {"EMBEDDINGS_MODEL"}

    def test_openai_api_key_is_not_satisfied_by_openai_api_key(self) -> None:
        env = _without(_openai_env(), "EMBEDDINGS_API_KEY")
        env["OPENAI_API_KEY"] = "sk-legacy"

        assert _named(_settings_error(env)) == {"EMBEDDINGS_API_KEY"}

    def test_sentence_transformers_requires_model_only(self) -> None:
        env = _stub_env(EMBEDDINGS_PROVIDER="sentence-transformers")

        assert _named(_settings_error(env)) == {"EMBEDDINGS_MODEL"}

        settings = load_settings({**env, "EMBEDDINGS_MODEL": "all-MiniLM-L6-v2"})
        assert settings.embeddings.provider == "sentence-transformers"
        assert settings.embeddings.model == "all-MiniLM-L6-v2"
        assert settings.embeddings.base_url is None
        assert settings.embeddings.api_key is None

    def test_stub_requires_no_model(self) -> None:
        settings = load_settings(_stub_env())

        assert settings.embeddings == EmbeddingsSettings(provider="stub", dim=8)

    def test_defaults_for_optional_variables(self) -> None:
        settings = load_settings(_stub_env())

        assert settings.database_url == _DB_URL
        assert settings.auth_file == "/nonexistent/auth.json"
        assert settings.host == "0.0.0.0"  # noqa: S104
        assert settings.port == 8080
        assert settings.log_level == "INFO"
        assert settings.migrate_on_startup is True
        assert settings.allowed_hosts == ()
        assert settings.embeddings.timeout_seconds == 10.0
        assert settings.search == SearchConfig()

    def test_every_variable_is_parsed_into_its_field(self) -> None:
        env = _openai_env(
            EMBEDDINGS_DIM="1536",
            EMBEDDINGS_TIMEOUT_SECONDS="2.5",
            RECALL_HOST="127.0.0.1",
            RECALL_PORT="9001",
            LOG_LEVEL="DEBUG",
            RECALL_DB_MIGRATE_ON_STARTUP="false",
            RECALL_ALLOWED_HOSTS="recall.example.com",
            RECALL_PROJECT_BOOST="0.08",
            RECALL_DEFAULT_LIMIT="7",
            RECALL_MAX_LIMIT="30",
            RECALL_SNIPPET_MAX_CHARS="120",
        )

        settings = load_settings(env)

        assert settings == Settings(
            database_url=_DB_URL,
            auth_file="/nonexistent/auth.json",
            embeddings=EmbeddingsSettings(
                provider="openai",
                dim=1536,
                model="text-embedding-3-small",
                base_url="https://embeddings.example.com/v1",
                api_key=_KEY_SENTINEL,
                timeout_seconds=2.5,
            ),
            search=SearchConfig(
                project_boost=0.08, default_limit=7, max_limit=30, snippet_max_chars=120
            ),
            host="127.0.0.1",
            port=9001,
            log_level="DEBUG",
            migrate_on_startup=False,
            allowed_hosts=("recall.example.com",),
        )

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", " FALSE ", "Off"])
    def test_falsy_values_disable_migrate_on_startup(self, raw: str) -> None:
        settings = load_settings(_stub_env(RECALL_DB_MIGRATE_ON_STARTUP=raw))

        assert settings.migrate_on_startup is False

    @pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " TRUE "])
    def test_other_values_enable_migrate_on_startup(self, raw: str) -> None:
        settings = load_settings(_stub_env(RECALL_DB_MIGRATE_ON_STARTUP=raw))

        assert settings.migrate_on_startup is True

    @pytest.mark.parametrize(("name", "value"), _INVALID_VALUES)
    def test_invalid_dim_port_timeout_reported_by_name(self, name: str, value: str) -> None:
        message = _settings_error(_stub_env(**{name: value}))

        assert "invalid" in message
        assert "missing required" not in message
        assert name in _named(message)

    @pytest.mark.parametrize(
        "name",
        ["EMBEDDINGS_PROVIDER", "EMBEDDINGS_DIM", "RECALL_PORT", "EMBEDDINGS_TIMEOUT_SECONDS"],
    )
    def test_invalid_entry_does_not_echo_the_value(self, name: str) -> None:
        message = _settings_error(_stub_env(**{name: "zz-bad-value-zz"}))

        assert name in message
        assert "zz-bad-value-zz" not in message

    def test_search_config_errors_are_folded_into_invalid(self) -> None:
        env = _stub_env(RECALL_DEFAULT_LIMIT="40", RECALL_MAX_LIMIT="30")

        message = _settings_error(env)

        assert "invalid" in message
        assert {"RECALL_DEFAULT_LIMIT", "RECALL_MAX_LIMIT"} <= _named(message)

    def test_all_problems_are_collected_into_one_error(self) -> None:
        env = {
            "EMBEDDINGS_PROVIDER": "openai",
            "EMBEDDINGS_DIM": "abc",
            "EMBEDDINGS_TIMEOUT_SECONDS": "soon",
            "RECALL_PORT": "abc",
            "RECALL_PROJECT_BOOST": "0.5",
        }

        message = _settings_error(env)

        assert "missing required environment variables" in message
        assert "invalid" in message
        assert _named(message) == {
            "DATABASE_URL",
            "RECALL_AUTH_FILE",
            *_OPENAI_REQUIRED,
            "EMBEDDINGS_DIM",
            "EMBEDDINGS_TIMEOUT_SECONDS",
            "RECALL_PORT",
            "RECALL_PROJECT_BOOST",
        }

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a.example.com", ("a.example.com",)),
            (
                " a.example.com , b.example.com:8080,c ",
                ("a.example.com", "b.example.com:8080", "c"),
            ),
            ("a,,b,", ("a", "b")),
            ("", ()),
        ],
    )
    def test_allowed_hosts_split_on_commas_and_trimmed(
        self, raw: str, expected: tuple[str, ...]
    ) -> None:
        settings = load_settings(_stub_env(RECALL_ALLOWED_HOSTS=raw))

        assert settings.allowed_hosts == expected

    def test_error_message_never_contains_secret_values(self) -> None:
        """I2."""
        env = _openai_env(DATABASE_URL=_DB_SENTINEL, RECALL_PORT="abc")

        message = _settings_error(env)

        assert "RECALL_PORT" in message
        assert _DB_SENTINEL not in message
        assert "sentinel-db-password" not in message
        assert _KEY_SENTINEL not in message

    def test_api_key_not_in_repr(self) -> None:
        """I3."""
        settings = load_settings(_openai_env())

        assert settings.embeddings.api_key == _KEY_SENTINEL
        assert _KEY_SENTINEL not in repr(settings)
        assert _KEY_SENTINEL not in repr(settings.embeddings)

    def test_database_url_not_in_repr(self) -> None:
        env = _stub_env(DATABASE_URL=_DB_SENTINEL)

        assert "sentinel-db-password" not in repr(load_settings(env))
        assert "sentinel-db-password" not in repr(load_db_settings(env))

    def test_retired_dims_variable_does_not_supply_the_dimension(self) -> None:
        env = _without(_stub_env(), "EMBEDDINGS_DIM")
        env["RECALL_" + "EMBEDDING_DIMS"] = "8"

        assert _named(_settings_error(env)) == {"EMBEDDINGS_DIM"}

    def test_loaders_ignore_the_process_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """I1: only the mapping passed in is consulted."""
        for name, value in _openai_env().items():
            monkeypatch.setenv(name, value)

        assert _named(_settings_error({})) == set(_ALWAYS_REQUIRED)
        assert _named(_db_settings_error({})) == {"DATABASE_URL", "EMBEDDINGS_DIM"}

    def test_settings_variables_lists_every_name_read(self) -> None:
        full = {
            **_openai_env(),
            "EMBEDDINGS_TIMEOUT_SECONDS": "10",
            "RECALL_HOST": "127.0.0.1",
            "RECALL_PORT": "8080",
            "LOG_LEVEL": "INFO",
            "RECALL_DB_MIGRATE_ON_STARTUP": "true",
            "RECALL_ALLOWED_HOSTS": "localhost",
            "RECALL_PROJECT_BOOST": "0.05",
            "RECALL_DEFAULT_LIMIT": "10",
            "RECALL_MAX_LIMIT": "50",
            "RECALL_SNIPPET_MAX_CHARS": "200",
        }
        assert set(full) == set(SETTINGS_VARIABLES)
        populated = _RecordingEnv(full)
        empty = _RecordingEnv({})

        load_settings(populated)
        with pytest.raises(SettingsError):
            load_settings(empty)

        assert populated.read == set(SETTINGS_VARIABLES)
        assert empty.read <= set(SETTINGS_VARIABLES)


# ---------------------------------------------------------------------------
# load_db_settings (REC-15)
# ---------------------------------------------------------------------------


class TestLoadDbSettings:
    _ENV = {"DATABASE_URL": _DB_URL, "EMBEDDINGS_DIM": "384"}  # noqa: RUF012

    def test_needs_only_database_url_and_dim(self) -> None:
        assert load_db_settings(self._ENV) == DbSettings(database_url=_DB_URL, embeddings_dim=384)

    def test_empty_env_lists_exactly_database_url_and_dim(self) -> None:
        message = _db_settings_error({})

        assert "missing required environment variables" in message
        assert _named(message) == {"DATABASE_URL", "EMBEDDINGS_DIM"}

    @pytest.mark.parametrize("name", ["DATABASE_URL", "EMBEDDINGS_DIM"])
    def test_empty_string_counts_as_unset(self, name: str) -> None:
        message = _db_settings_error({**self._ENV, name: ""})

        assert "missing required environment variables" in message
        assert _named(message) == {name}

    @pytest.mark.parametrize("provider", ["openai", "sentence-transformers", "stub"])
    def test_provider_dependent_variables_are_not_required(self, provider: str) -> None:
        settings = load_db_settings({**self._ENV, "EMBEDDINGS_PROVIDER": provider})

        assert settings.embeddings_dim == 384

    @pytest.mark.parametrize(("name", "value"), _INVALID_VALUES)
    def test_any_set_and_invalid_variable_is_reported_by_name(self, name: str, value: str) -> None:
        message = _db_settings_error({**self._ENV, name: value})

        assert "invalid" in message
        assert "missing required" not in message
        assert name in _named(message)

    def test_missing_and_invalid_reported_together(self) -> None:
        message = _db_settings_error({"RECALL_PORT": "abc"})

        assert _named(message) == {"DATABASE_URL", "EMBEDDINGS_DIM", "RECALL_PORT"}

    def test_error_message_never_contains_secret_values(self) -> None:
        """I2."""
        env = _openai_env(DATABASE_URL=_DB_SENTINEL, EMBEDDINGS_DIM="abc")

        message = _db_settings_error(env)

        assert "sentinel-db-password" not in message
        assert _KEY_SENTINEL not in message


# ---------------------------------------------------------------------------
# Consumers of Settings: create_app and configure_telemetry (REC-15)
# ---------------------------------------------------------------------------


class TestSettingsConsumers:
    def test_create_app_takes_settings_and_stashes_database_url(self, tmp_path: Path) -> None:
        settings = load_settings(_stub_env(RECALL_AUTH_FILE=_auth_file(tmp_path)))

        app = create_app(settings)

        assert app.state.conn_string == _DB_URL

    def test_create_app_fails_when_auth_file_does_not_exist(self, tmp_path: Path) -> None:
        settings = load_settings(_stub_env(RECALL_AUTH_FILE=str(tmp_path / "absent.json")))

        with pytest.raises(StartupError, match="RECALL_AUTH_FILE"):
            create_app(settings)

    def test_configure_telemetry_reads_endpoint_from_the_mapping(
        self,
        captured_logs: list[MutableMapping[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        configure_telemetry({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"})

        events = [e for e in captured_logs if e["event"] == "otel_export_unimplemented"]
        assert [e["endpoint"] for e in events] == ["http://collector:4318"]

    def test_configure_telemetry_ignores_the_process_environment(
        self,
        captured_logs: list[MutableMapping[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

        configure_telemetry({})

        assert not [e for e in captured_logs if e["event"] == "otel_export_unimplemented"]


# ---------------------------------------------------------------------------
# Source-level invariants (REC-15)
# ---------------------------------------------------------------------------


_ENV_NAMES = frozenset({"environ", "environb", "getenv"})


def _is_os_attribute(node: ast.AST) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr not in _ENV_NAMES:
        return False
    return isinstance(node.value, ast.Name) and node.value.id == "os"


def _access_count(node: ast.AST) -> int:
    """How many process-environment accesses ``node`` itself makes."""
    if isinstance(node, ast.ImportFrom) and node.module == "os":
        return sum(alias.name in _ENV_NAMES for alias in node.names)
    return int(_is_os_attribute(node))


def _environment_reads(tree: ast.AST, function: str = "<module>") -> Iterator[str]:
    """Yield the enclosing function name of every process-environment access."""
    for node in ast.iter_child_nodes(tree):
        inner = function
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            inner = node.name
        yield from [inner] * _access_count(node)
        yield from _environment_reads(node, inner)


class TestSourceInvariants:
    def test_only_cli_main_touches_the_process_environment(self) -> None:
        """I1: exactly one access in ``src/recall``, inside ``cli.main``."""
        package = _REPO_ROOT / "src" / "recall"

        hits = [
            (path.relative_to(package).as_posix(), function)
            for path in sorted(package.rglob("*.py"))
            for function in _environment_reads(ast.parse(path.read_text(encoding="utf-8")))
        ]

        assert hits == [("cli.py", "main")]

    def test_retired_dims_variable_is_read_nowhere(self) -> None:
        retired = "RECALL_" + "EMBEDDING_DIMS"

        offenders = [
            str(path.relative_to(_REPO_ROOT))
            for root in ("src", "tests")
            for path in sorted((_REPO_ROOT / root).rglob("*.py"))
            if retired in path.read_text(encoding="utf-8")
        ]

        assert offenders == []


# ---------------------------------------------------------------------------
# CLI startup — subprocess (REC-15)
# ---------------------------------------------------------------------------

_COMMANDS = [["serve"], ["db", "migrate"]]


class TestServeStartup:
    def test_serve_with_empty_env_exits_one_listing_missing(self, tmp_path: Path) -> None:
        result = _run_cli(["serve"], {}, tmp_path)

        _assert_clean_failure(result)
        reports = [line for line in result.stderr.splitlines() if "DATABASE_URL" in line]
        assert len(reports) == 1, result.stderr
        assert _named(reports[0]) == set(_ALWAYS_REQUIRED)

    def test_serve_openai_without_endpoint_and_key_names_both(self, tmp_path: Path) -> None:
        env = _without(_openai_env(), "EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY")

        result = _run_cli(["serve", "--dry-run"], env, tmp_path)

        _assert_clean_failure(result)
        assert _named(result.stderr) == {"EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY"}

    def test_db_migrate_without_dim_exits_one(self, tmp_path: Path) -> None:
        result = _run_cli(["db", "migrate"], {"DATABASE_URL": _DB_URL}, tmp_path)

        _assert_clean_failure(result)
        assert _named(result.stderr) == {"EMBEDDINGS_DIM"}

    def test_db_migrate_with_empty_env_names_both_required(self, tmp_path: Path) -> None:
        result = _run_cli(["db", "migrate"], {}, tmp_path)

        _assert_clean_failure(result)
        assert _named(result.stderr) == {"DATABASE_URL", "EMBEDDINGS_DIM"}

    @pytest.mark.parametrize("command", _COMMANDS, ids=["serve", "db-migrate"])
    def test_non_numeric_port_reported_by_name_without_traceback(
        self, command: list[str], tmp_path: Path
    ) -> None:
        result = _run_cli(command, _stub_env(RECALL_PORT="abc"), tmp_path)

        _assert_clean_failure(result)
        assert "RECALL_PORT" in result.stderr

    @pytest.mark.parametrize("command", _COMMANDS, ids=["serve", "db-migrate"])
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("EMBEDDINGS_PROVIDER", "cohere"),
            ("EMBEDDINGS_DIM", "0"),
            ("EMBEDDINGS_TIMEOUT_SECONDS", "soon"),
            ("RECALL_PROJECT_BOOST", "0.5"),
        ],
    )
    def test_invalid_variable_reported_by_name_without_traceback(
        self, command: list[str], name: str, value: str, tmp_path: Path
    ) -> None:
        result = _run_cli(command, _stub_env(**{name: value}), tmp_path)

        _assert_clean_failure(result)
        assert name in result.stderr

    @pytest.mark.parametrize("command", _COMMANDS, ids=["serve", "db-migrate"])
    def test_failure_output_never_contains_secret_values(
        self, command: list[str], tmp_path: Path
    ) -> None:
        """I2 at the CLI boundary."""
        env = _openai_env(DATABASE_URL=_DB_SENTINEL, RECALL_PORT="abc")

        result = _run_cli(command, env, tmp_path)

        _assert_clean_failure(result)
        output = result.stdout + result.stderr
        assert "sentinel-db-password" not in output
        assert _KEY_SENTINEL not in output

    def test_serve_dry_run_with_stub_env_exits_zero(self, tmp_path: Path) -> None:
        env = _stub_env(RECALL_AUTH_FILE=_auth_file(tmp_path), RECALL_DB_MIGRATE_ON_STARTUP="false")

        result = _run_cli(["serve", "--dry-run"], env, tmp_path)

        assert result.returncode == 0, result.stderr

    def test_serve_with_unreadable_auth_file_logs_startup_failed(self, tmp_path: Path) -> None:
        env = _stub_env(
            RECALL_AUTH_FILE=str(tmp_path / "absent.json"),
            RECALL_DB_MIGRATE_ON_STARTUP="false",
        )

        result = _run_cli(["serve", "--dry-run"], env, tmp_path)

        assert result.returncode == 1
        assert "startup_failed" in result.stdout

    def test_help_does_not_read_settings(self, tmp_path: Path) -> None:
        result = _run_cli(["serve", "--help"], {"RECALL_PORT": "abc"}, tmp_path)

        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# CLI flags override settings — in process (REC-15)
# ---------------------------------------------------------------------------


@pytest.fixture
def serve_calls(monkeypatch: pytest.MonkeyPatch, reset_logging: None) -> list[dict[str, Any]]:
    """Replace the blocking ``uvicorn.run`` and record the arguments it receives."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


def _serve(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flags: list[str], **env: str) -> None:
    """Call ``main`` with an isolated process environment."""
    full = _stub_env(
        RECALL_AUTH_FILE=_auth_file(tmp_path), RECALL_DB_MIGRATE_ON_STARTUP="false", **env
    )
    monkeypatch.setattr(os, "environ", full)
    main(["serve", *flags])


class TestServeFlags:
    def test_defaults_apply_without_flags_or_variables(
        self,
        serve_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _serve(monkeypatch, tmp_path, [])

        assert len(serve_calls) == 1
        assert serve_calls[0]["host"] == "0.0.0.0"  # noqa: S104
        assert serve_calls[0]["port"] == 8080
        assert logging.getLogger().level == logging.INFO

    def test_settings_apply_when_no_flag_is_given(
        self,
        serve_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _serve(
            monkeypatch,
            tmp_path,
            [],
            RECALL_HOST="127.0.0.2",
            RECALL_PORT="9001",
            LOG_LEVEL="WARNING",
        )

        assert serve_calls[0]["host"] == "127.0.0.2"
        assert serve_calls[0]["port"] == 9001
        assert logging.getLogger().level == logging.WARNING

    def test_cli_flags_override_settings(
        self,
        serve_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _serve(
            monkeypatch,
            tmp_path,
            ["--host", "127.0.0.3", "--port", "9002", "--log-level", "DEBUG"],
            RECALL_HOST="127.0.0.2",
            RECALL_PORT="9001",
            LOG_LEVEL="ERROR",
        )

        assert serve_calls[0]["host"] == "127.0.0.3"
        assert serve_calls[0]["port"] == 9002
        assert logging.getLogger().level == logging.DEBUG

    def test_only_the_given_flag_overrides(
        self,
        serve_calls: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _serve(
            monkeypatch,
            tmp_path,
            ["--port", "9002"],
            RECALL_HOST="127.0.0.2",
            RECALL_PORT="9001",
            LOG_LEVEL="ERROR",
        )

        assert serve_calls[0]["host"] == "127.0.0.2"
        assert serve_calls[0]["port"] == 9002
        assert logging.getLogger().level == logging.ERROR


# ---------------------------------------------------------------------------
# One dimension for schema and store — real Postgres (REC-15, ADR-0012)
# ---------------------------------------------------------------------------


async def _vector_column_type(conn_string: str) -> str:
    async with await psycopg.AsyncConnection.connect(conn_string) as conn:
        cursor = await conn.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'store_vectors'::regclass AND attname = 'embedding'"
        )
        row = await cursor.fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.integration
class TestEmbeddingsDimension:
    async def test_ensure_schema_uses_the_dims_parameter(self, pg_conn: str) -> None:
        await ensure_schema(pg_conn, 8)

        assert await _vector_column_type(pg_conn) == "vector(8)"

    async def test_db_migrate_creates_schema_with_only_url_and_dim(
        self, pg_conn: str, tmp_path: Path
    ) -> None:
        env = {"DATABASE_URL": pg_conn, "EMBEDDINGS_DIM": "12"}

        result = _run_cli(["db", "migrate"], env, tmp_path)

        assert result.returncode == 0, result.stderr
        assert await _vector_column_type(pg_conn) == "vector(12)"

    async def test_app_store_uses_the_configured_dim(self, pg_conn: str, tmp_path: Path) -> None:
        """A save embeds and persists when schema and app share a non-default dim."""
        from tests.test_e2e_phase1 import _e2e_client, _save_params, _unpack_result

        settings = load_settings(
            _stub_env(DATABASE_URL=pg_conn, RECALL_AUTH_FILE=_auth_file(tmp_path))
        )
        await ensure_schema(settings.database_url, settings.embeddings.dim)
        headers = {"Authorization": "Bearer test-token"}

        async with _e2e_client(create_app(settings), headers) as client:
            payload = _unpack_result(await client.call_tool("memory_save", _save_params()))

        assert "id" in payload, payload


@pytest.mark.parametrize("loader", [load_settings, load_db_settings])
def test_unparseable_database_url_is_reported_without_echoing_it(loader: Any) -> None:
    """REC-15 I2: libpq would quote a malformed connection string in its own error."""
    env = {
        "DATABASE_URL": "sentinel-not-a-dsn",
        "RECALL_AUTH_FILE": "/nonexistent",
        "EMBEDDINGS_PROVIDER": "stub",
        "EMBEDDINGS_DIM": "8",
    }

    with pytest.raises(SettingsError) as exc_info:
        loader(env)

    assert "DATABASE_URL" in str(exc_info.value)
    assert "sentinel-not-a-dsn" not in str(exc_info.value)
