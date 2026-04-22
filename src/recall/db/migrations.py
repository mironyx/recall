"""In-app DDL migration runner (ADR-0013)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

import psycopg
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig
from psycopg import errors as pg_errors

MIGRATIONS_DIR: Path = Path(__file__).resolve().parent.parent / "migrations"

# 64-bit constant used as the pg_advisory_lock key for migration runs.
# Any stable integer works; derived from ASCII "RECALL" for readability in logs.
_ADVISORY_LOCK_KEY = 0x5245_4341_4C4C  # "RECALL"

# Phase-0 placeholder — store_vectors needs a concrete dim at DDL time.
# Default matches OpenAI text-embedding-3-small; will be parameterised once
# EMBEDDINGS_DIM wiring lands (ADR-0008).
_DEFAULT_DIMS = 1536


def _phase0_index_config() -> PostgresIndexConfig:
    """Return a minimal PostgresIndexConfig sufficient for ``setup()`` DDL.

    ``setup()`` only reads ``dims`` and ``ann_index_config`` from the config
    when creating ``store_vectors``; ``embed`` is required by type but never
    invoked during DDL. Phase 0 uses HNSW as the ANN kind — it is the upstream
    default and keeps us on a supported configuration until the embeddings
    wiring (ADR-0008) pins final values.
    """

    def _noop_embed(texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Phase-0 placeholder embed called at runtime; wire a real provider.")

    raw_dims = os.environ.get("RECALL_EMBEDDING_DIMS")
    if raw_dims is None:
        dims = _DEFAULT_DIMS
    else:
        try:
            dims = int(raw_dims)
        except ValueError as exc:
            raise ValueError(f"RECALL_EMBEDDING_DIMS must be an integer, got {raw_dims!r}") from exc
    return PostgresIndexConfig(dims=dims, embed=_noop_embed)


_CREATE_LEDGER_SQL = """\
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _load_pending(applied: set[str]) -> list[tuple[str, str]]:
    """Read migration files under :data:`MIGRATIONS_DIR` and return a list of
    ``(version, sql_text)`` pairs for anything not yet in ``applied``, sorted
    by filename. Runs synchronously; callers offload via ``asyncio.to_thread``.
    """
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [(f.stem, f.read_text()) for f in files if f.stem not in applied]


async def _run_store_setup(conn_string: str) -> None:
    """Run AsyncPostgresStore.setup() with retry on concurrent-DDL races.

    Postgres' ``CREATE TABLE IF NOT EXISTS`` is not race-safe against
    simultaneous DDL: two concurrent creators can both observe the table as
    missing and one of them hits a ``UniqueViolation`` on ``pg_type``. We
    retry a small number of times — by the time the retry runs the loser sees
    the tables already present and ``IF NOT EXISTS`` short-circuits.
    """
    for attempt in range(5):
        try:
            async with AsyncPostgresStore.from_conn_string(
                conn_string, index=_phase0_index_config()
            ) as store:
                await store.setup()
            return
        except pg_errors.UniqueViolation:
            if attempt == 4:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))


async def apply_pending(conn_string: str) -> list[str]:
    """Apply all pending SQL migrations in filename order.

    Returns the list of newly applied version strings (e.g. ``["0001_initial",
    "0002_projects"]``). Returns an empty list if everything is already
    applied. Each migration runs in its own transaction; a failure rolls the
    offending transaction back and re-raises, leaving prior migrations
    applied.
    """
    # 1. Ensure the LangGraph store tables exist. Idempotent; the retry
    #    loop handles the CREATE TABLE IF NOT EXISTS race on pg_type that
    #    two simultaneous callers can trigger.
    await _run_store_setup(conn_string)

    # 2. Open a psycopg connection for the DDL runner.
    async with await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn:
        # 2a. Ensure our own ledger exists. Retry on the same pg_type race.
        for attempt in range(5):
            try:
                await conn.execute(_CREATE_LEDGER_SQL)
                break
            except pg_errors.UniqueViolation:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.1 * (attempt + 1))

        # 2b. Acquire a session advisory lock so concurrent runners serialise
        #     on the SQL-migration section. Per-migration COMMITs happen
        #     while holding the lock, so a partial failure leaves successful
        #     earlier migrations on disk.
        await conn.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT version FROM schema_migrations")
                applied: set[str] = {row[0] for row in await cur.fetchall()}

            pending = await asyncio.to_thread(_load_pending, applied)

            newly_applied: list[str] = []
            for version, sql_text in pending:
                async with conn.transaction():
                    await conn.execute(sql_text)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                newly_applied.append(version)

            return newly_applied
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
