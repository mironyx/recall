"""Evaluator tests for REC-15 (LLD §LLD-e4-settings): search variables in ``SettingsError``."""

from __future__ import annotations

import subprocess
import sys
import traceback
from collections.abc import Callable, MutableMapping
from typing import Any

import httpx
import pytest
from tests.conftest import make_settings, stub_env

from recall.server import create_app
from recall.settings import SettingsError, load_db_settings, load_settings

Loader = Callable[[dict[str, str]], object]

_ENV = {
    "DATABASE_URL": "postgresql://nouser:nopass@127.0.0.1:1/nodb",
    "RECALL_AUTH_FILE": "/nonexistent/auth.json",
    "EMBEDDINGS_PROVIDER": "stub",
    "EMBEDDINGS_DIM": "8",
}


@pytest.mark.parametrize("loader", [load_settings, load_db_settings])
def test_every_invalid_search_variable_is_reported_at_once(loader: Loader) -> None:
    """§4.1: every variable is checked and all problems are collected."""
    names = ("RECALL_PROJECT_BOOST", "RECALL_DEFAULT_LIMIT", "RECALL_MAX_LIMIT")

    with pytest.raises(SettingsError) as excinfo:
        loader(_ENV | dict.fromkeys(names, "abc"))

    assert [name for name in names if name not in str(excinfo.value)] == []


@pytest.mark.parametrize(
    "name", ["RECALL_PROJECT_BOOST", "RECALL_DEFAULT_LIMIT", "RECALL_SNIPPET_MAX_CHARS"]
)
def test_invalid_search_entry_does_not_echo_the_value(name: str) -> None:
    """§4.1 types: invalid entries carry the name and a reason, never the value."""
    with pytest.raises(SettingsError) as excinfo:
        load_settings(_ENV | {name: "zz-bad-value-zz"})

    assert "zz-bad-value-zz" not in str(excinfo.value)


@pytest.mark.parametrize("loader", [load_settings, load_db_settings])
def test_non_utf8_database_url_is_a_settings_error(loader: Loader) -> None:
    """A non-UTF-8 environment byte reaches Python as a lone surrogate."""
    with pytest.raises(SettingsError) as excinfo:
        loader(_ENV | {"DATABASE_URL": "host=\udcff"})

    assert "DATABASE_URL" in str(excinfo.value)


@pytest.mark.parametrize("command", [["db", "migrate"], ["serve"]])
def test_connection_failure_never_quotes_the_database_url(command: list[str]) -> None:
    """I2: an unescaped "@" makes libpq read part of the password as the host name."""
    tail = "sentineltail"
    password = "@".join(["head", tail])
    url = "postgresql://" + "nouser:" + password + "@127.0.0.1:1/nodb"
    env = stub_env(url) | {"DATABASE_URL": url}

    result = subprocess.run(
        [sys.executable, "-m", "recall.cli", *command],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    assert result.returncode == 1
    assert "schema" in result.stdout + result.stderr
    assert tail not in result.stdout + result.stderr


def _url_with_unescaped_password(tail: str) -> str:
    password = "@".join(["head", tail])
    return "postgresql://" + "nouser:" + password + "@127.0.0.1:1/nodb"


async def test_lifespan_connection_failure_never_quotes_the_database_url() -> None:
    """With auto-migrate off, the first connection is made in the app lifespan."""
    tail = "sentineltail"
    app = create_app(make_settings(_url_with_unescaped_password(tail)))

    with pytest.raises(Exception) as excinfo:
        async with app.router.lifespan_context(app):
            pass

    printed = "".join(traceback.format_exception(excinfo.value))
    assert "OperationalError" in printed
    assert tail not in printed


@pytest.mark.parametrize("tail", ["sentineltail", "sentinel:tail"])
async def test_readyz_never_quotes_the_database_url(
    tail: str, captured_logs: list[MutableMapping[str, Any]]
) -> None:
    app = create_app(make_settings(_url_with_unescaped_password(tail)))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert "sentinel" not in response.text + str(captured_logs)
