"""Typed settings, loaded once from an environment mapping (LLD §LLD-e4-settings).

Nothing here touches the process environment: ``cli.main`` passes it in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, get_args

import psycopg
from psycopg.conninfo import conninfo_to_dict

from recall.config import SearchConfig, load_search_config
from recall.errors import ValidationError

ProviderName = Literal["openai", "sentence-transformers", "stub"]

_PROVIDERS: dict[str, ProviderName] = {name: name for name in get_args(ProviderName)}
_FALSY_ENV_VALUES = frozenset({"0", "false", "no", "off", ""})
_MAX_PORT = 65535
_ALWAYS_REQUIRED = ("DATABASE_URL", "RECALL_AUTH_FILE", "EMBEDDINGS_PROVIDER", "EMBEDDINGS_DIM")
_DB_REQUIRED = ("DATABASE_URL", "EMBEDDINGS_DIM")
_SEARCH_CASTS: dict[str, type[int] | type[float]] = {
    "RECALL_PROJECT_BOOST": float,
    "RECALL_DEFAULT_LIMIT": int,
    "RECALL_MAX_LIMIT": int,
    "RECALL_SNIPPET_MAX_CHARS": int,
}
# Variables `load_search_config` checks together, with a value-free reason for each rule.
_SEARCH_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("RECALL_PROJECT_BOOST",), "outside the ADR-0010 bounds"),
    (("RECALL_DEFAULT_LIMIT", "RECALL_MAX_LIMIT"), "default limit exceeds max limit"),
)
_PROVIDER_REQUIRED: dict[ProviderName, tuple[str, ...]] = {
    "openai": ("EMBEDDINGS_MODEL", "EMBEDDINGS_BASE_URL", "EMBEDDINGS_API_KEY"),
    "sentence-transformers": ("EMBEDDINGS_MODEL",),
    "stub": (),
}

#: Every variable name ``load_settings`` reads.
SETTINGS_VARIABLES: tuple[str, ...] = (
    "DATABASE_URL",
    "RECALL_AUTH_FILE",
    "EMBEDDINGS_PROVIDER",
    "EMBEDDINGS_DIM",
    "EMBEDDINGS_MODEL",
    "EMBEDDINGS_BASE_URL",
    "EMBEDDINGS_API_KEY",
    "EMBEDDINGS_TIMEOUT_SECONDS",
    "RECALL_HOST",
    "RECALL_PORT",
    "LOG_LEVEL",
    "RECALL_DB_MIGRATE_ON_STARTUP",
    "RECALL_ALLOWED_HOSTS",
    "RECALL_PROJECT_BOOST",
    "RECALL_DEFAULT_LIMIT",
    "RECALL_MAX_LIMIT",
    "RECALL_SNIPPET_MAX_CHARS",
)


@dataclass(frozen=True)
class EmbeddingsSettings:
    provider: ProviderName
    dim: int
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    auth_file: str
    embeddings: EmbeddingsSettings
    search: SearchConfig
    host: str = "0.0.0.0"  # noqa: S104 — container convention (cli.py)
    port: int = 8080
    log_level: str = "INFO"
    migrate_on_startup: bool = True
    allowed_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class DbSettings:
    database_url: str = field(repr=False)
    embeddings_dim: int


class SettingsError(Exception):
    """Every missing and invalid variable at once. Never carries a secret value."""

    def __init__(self, missing: Sequence[str] = (), invalid: Sequence[str] = ()) -> None:
        self.missing = tuple(missing)
        self.invalid = tuple(invalid)
        parts = []
        if self.missing:
            parts.append(f"missing required environment variables: {', '.join(self.missing)}")
        if self.invalid:
            parts.append(f"invalid: {', '.join(self.invalid)}")
        super().__init__("; ".join(parts))


@dataclass(frozen=True)
class _Optional:
    """The optional variables, parsed: shared by both loaders."""

    provider: ProviderName | None
    dim: int | None
    timeout_seconds: float
    port: int
    search: SearchConfig


# Justification: one required-variable rule shared by both loaders and the provider check.
def _require(env: Mapping[str, str], names: Sequence[str], missing: list[str]) -> dict[str, str]:
    """Return the set (non-empty) values of ``names``; record the others as missing."""
    missing.extend(name for name in names if not env.get(name))
    return {name: env[name] for name in names if env.get(name)}


# Justification: the one conversion and error report shared by the numeric parsers.
def _convert[T: (int, float)](
    env: Mapping[str, str], name: str, invalid: list[str], cast: type[T]
) -> T | None:
    """Cast ``name``; None when unset or not convertible."""
    raw = env.get(name)
    if not raw:
        return None
    try:
        return cast(raw)
    except ValueError:
        invalid.append(f"{name} (not a valid {cast.__name__})")
        return None


# Justification: shared by the dimension and port variables.
def _parse_int(
    env: Mapping[str, str], name: str, invalid: list[str], *, minimum: int
) -> int | None:
    """Parse ``name`` as an integer of at least ``minimum``; None when unset or invalid."""
    value = _convert(env, name, invalid, int)
    if value is not None and value < minimum:
        invalid.append(f"{name} (must be at least {minimum})")
        return None
    return value


# Justification: only the port has an upper bound; uvicorn would fail on it with a traceback.
def _parse_port(env: Mapping[str, str], invalid: list[str]) -> int:
    port = _parse_int(env, "RECALL_PORT", invalid, minimum=1)
    if port is None:
        return Settings.port
    if port > _MAX_PORT:
        invalid.append(f"RECALL_PORT (must be at most {_MAX_PORT})")
    return port


# Justification: keeps float validation out of the loaders (complexity gate).
def _parse_float(env: Mapping[str, str], name: str, invalid: list[str]) -> float | None:
    """Parse ``name`` as a positive finite number; None when unset or invalid."""
    value = _convert(env, name, invalid, float)
    if value is not None and not 0 < value < math.inf:  # also rejects nan
        invalid.append(f"{name} (must be a positive number)")
        return None
    return value


# Justification: the falsy vocabulary is a unit of its own, testable apart from the loader.
def _parse_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSY_ENV_VALUES


# Justification: list parsing is separable and testable.
def _parse_hosts(raw: str) -> tuple[str, ...]:
    return tuple(host.strip() for host in raw.split(",") if host.strip())


# Justification: never echoes the rejected value; keeps the loaders flat.
def _parse_provider(env: Mapping[str, str], invalid: list[str]) -> ProviderName | None:
    raw = env.get("EMBEDDINGS_PROVIDER")
    if not raw:
        return None
    provider = _PROVIDERS.get(raw)
    if provider is None:
        invalid.append(f"EMBEDDINGS_PROVIDER (expected one of: {', '.join(_PROVIDERS)})")
    return provider


# Justification: libpq's parse errors quote the string, so it is rejected here without echoing it.
def _check_database_url(env: Mapping[str, str], invalid: list[str]) -> None:
    # TODO: libpq also accepts key=value strings, which asyncpg (/readyz) rejects.
    raw = env.get("DATABASE_URL")
    if not raw:
        return
    try:
        conninfo_to_dict(raw)
    except (psycopg.ProgrammingError, UnicodeError):
        invalid.append("DATABASE_URL (not a valid Postgres connection string)")


# Justification: decides whether a search variable can reach the rule checks (complexity gate).
def _is_castable(name: str, raw: str, invalid: list[str]) -> bool:
    cast = _SEARCH_CASTS[name]
    try:
        cast(raw)
    except ValueError:
        invalid.append(f"{name} (not a valid {cast.__name__})")
        return False
    return True


# Justification: `load_search_config` stops at its first problem and quotes the value.
def _search(env: Mapping[str, str], invalid: list[str]) -> SearchConfig:
    """Report every bad search variable by name; the result is defaults if any is bad."""
    given = {name: env[name] for name in _SEARCH_CASTS if name in env}
    usable = {name: raw for name, raw in given.items() if _is_castable(name, raw, invalid)}
    unparsed = given.keys() - usable.keys()
    for names, reason in _SEARCH_RULES:
        if unparsed.isdisjoint(names) and not _satisfies(usable, names):
            invalid.append(f"{', '.join(names)} ({reason})")
            unparsed |= set(names)
    if unparsed:
        return SearchConfig()
    return load_search_config(usable)


# Justification: runs one rule in isolation so a failure cannot hide another.
def _satisfies(values: Mapping[str, str], names: Sequence[str]) -> bool:
    try:
        load_search_config({name: values[name] for name in names if name in values})
    except ValidationError:
        return False
    return True


# Justification: reused by both loaders so `db migrate` rejects the same bad values as `serve`.
def _parse_optional(env: Mapping[str, str], invalid: list[str]) -> _Optional:
    """Validate every typed variable that is set."""
    _check_database_url(env, invalid)
    provider = _parse_provider(env, invalid)
    dim = _parse_int(env, "EMBEDDINGS_DIM", invalid, minimum=1)
    timeout = _parse_float(env, "EMBEDDINGS_TIMEOUT_SECONDS", invalid)
    return _Optional(
        provider=provider,
        dim=dim,
        timeout_seconds=EmbeddingsSettings.timeout_seconds if timeout is None else timeout,
        port=_parse_port(env, invalid),
        search=_search(env, invalid),
    )


# Justification: the provider-dependent requirements are one cohesive step (complexity gate).
def _embeddings(
    env: Mapping[str, str], parsed: _Optional, missing: list[str]
) -> EmbeddingsSettings | None:
    """Build the embeddings settings; None when provider or dimension is unusable."""
    if parsed.provider is None:
        return None
    _require(env, _PROVIDER_REQUIRED[parsed.provider], missing)
    if parsed.dim is None:
        return None
    return EmbeddingsSettings(
        provider=parsed.provider,
        dim=parsed.dim,
        model=env.get("EMBEDDINGS_MODEL") or None,
        base_url=env.get("EMBEDDINGS_BASE_URL") or None,
        api_key=env.get("EMBEDDINGS_API_KEY") or None,
        timeout_seconds=parsed.timeout_seconds,
    )


def load_settings(env: Mapping[str, str]) -> Settings:
    """Build ``Settings`` from ``env``; raises ``SettingsError`` listing every problem."""
    missing: list[str] = []
    invalid: list[str] = []
    required = _require(env, _ALWAYS_REQUIRED, missing)
    parsed = _parse_optional(env, invalid)
    embeddings = _embeddings(env, parsed, missing)
    if missing or invalid:
        raise SettingsError(missing, invalid)
    assert embeddings is not None  # None only when a problem was recorded
    return Settings(
        database_url=required["DATABASE_URL"],
        auth_file=required["RECALL_AUTH_FILE"],
        embeddings=embeddings,
        search=parsed.search,
        host=env.get("RECALL_HOST") or Settings.host,
        port=parsed.port,
        log_level=env.get("LOG_LEVEL") or Settings.log_level,
        migrate_on_startup=_parse_bool(
            env, "RECALL_DB_MIGRATE_ON_STARTUP", Settings.migrate_on_startup
        ),
        allowed_hosts=_parse_hosts(env.get("RECALL_ALLOWED_HOSTS", "")),
    )


def load_db_settings(env: Mapping[str, str]) -> DbSettings:
    """Build ``DbSettings`` (for ``recall db migrate``); raises ``SettingsError``.

    Only ``DATABASE_URL`` and ``EMBEDDINGS_DIM`` are required; any other variable
    that is set and invalid is still reported.
    """
    missing: list[str] = []
    invalid: list[str] = []
    required = _require(env, _DB_REQUIRED, missing)
    parsed = _parse_optional(env, invalid)
    if missing or invalid:
        raise SettingsError(missing, invalid)
    assert parsed.dim is not None  # required above, so unset or invalid has raised
    return DbSettings(database_url=required["DATABASE_URL"], embeddings_dim=parsed.dim)
