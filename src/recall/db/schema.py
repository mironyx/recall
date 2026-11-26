"""Idempotent schema setup (ADR-0013 revised, ADR-0014)."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig

_SCOPE_CHECK_SQL = """\
DO $$ BEGIN
    ALTER TABLE store ADD CONSTRAINT store_scope_invariant CHECK (
        prefix = 'global._'
        OR (prefix LIKE 'project.%' AND prefix != 'project._')
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""


def _index_config(dims: int) -> PostgresIndexConfig:
    """Return a minimal ``PostgresIndexConfig`` sufficient for ``setup()`` DDL.

    ``setup()`` only reads ``dims`` and ``ann_index_config`` when creating
    ``store_vectors``; ``embed`` is required by type but never invoked during
    DDL.  Uses the upstream HNSW default.
    """

    def _noop_embed(texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        raise RuntimeError("DDL-only index config; never embeds.")

    return PostgresIndexConfig(dims=dims, embed=_noop_embed)


# Justification: one redaction rule shared by the CLI and the app lifespan (LLD I2).
def describe_db_error(exc: Exception) -> str:
    """Describe a database failure without revealing any part of ``DATABASE_URL``.

    Only psycopg errors carrying a SQLSTATE (a statement the server rejected) are
    quoted. Connection failures have none, and their text can contain the host,
    user or part of a password.
    """
    if isinstance(exc, psycopg.Error) and exc.sqlstate:
        return f"{type(exc).__name__}: {exc}"
    return (
        f"{type(exc).__name__} (details withheld as they can quote DATABASE_URL; "
        "check that it is correct and Postgres is reachable)"
    )


async def ensure_schema(conn_string: str, dims: int) -> None:
    """Create all required tables and constraints.  Idempotent.

    ``dims`` fixes the ``vector(N)`` column when ``store_vectors`` is first created.

    1. ``AsyncPostgresStore.setup()`` — ``store``, ``store_vectors``, internal ledgers.
    2. Scope CHECK constraint on the ``store`` table (ADR-0001 / ADR-0002).

    The ``projects`` table is deferred (ADR-0014).
    """
    async with AsyncPostgresStore.from_conn_string(conn_string, index=_index_config(dims)) as store:
        await store.setup()

    async with await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn:
        await conn.execute(_SCOPE_CHECK_SQL)
