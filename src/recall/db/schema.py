"""Idempotent schema setup (ADR-0013 revised, ADR-0014)."""

from __future__ import annotations

import os
from collections.abc import Sequence

import psycopg
from langgraph.store.postgres import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig

_DEFAULT_DIMS = 1536

_SCOPE_CHECK_SQL = """\
DO $$ BEGIN
    ALTER TABLE store ADD CONSTRAINT store_scope_invariant CHECK (
        prefix = 'global._'
        OR (prefix LIKE 'project.%' AND prefix != 'project._')
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""


def _phase0_index_config() -> PostgresIndexConfig:
    """Return a minimal ``PostgresIndexConfig`` sufficient for ``setup()`` DDL.

    ``setup()`` only reads ``dims`` and ``ann_index_config`` when creating
    ``store_vectors``; ``embed`` is required by type but never invoked during
    DDL.  Phase 0 uses the upstream HNSW default.
    """

    def _noop_embed(texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        raise RuntimeError("Phase-0 placeholder; wire a real provider.")

    raw_dims = os.environ.get("RECALL_EMBEDDING_DIMS")
    dims = int(raw_dims) if raw_dims else _DEFAULT_DIMS
    return PostgresIndexConfig(dims=dims, embed=_noop_embed)


async def ensure_schema(conn_string: str) -> None:
    """Create all required tables and constraints.  Idempotent.

    1. ``AsyncPostgresStore.setup()`` — ``store``, ``store_vectors``, internal ledgers.
    2. Scope CHECK constraint on the ``store`` table (ADR-0001 / ADR-0002).

    The ``projects`` table is deferred (ADR-0014).
    """
    async with AsyncPostgresStore.from_conn_string(
        conn_string, index=_phase0_index_config()
    ) as store:
        await store.setup()

    async with await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as conn:
        await conn.execute(_SCOPE_CHECK_SQL)
