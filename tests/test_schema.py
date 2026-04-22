"""Integration tests for idempotent schema setup (E0.4, revised ADR-0013).

Exercises ``ensure_schema`` against a real Postgres+pgvector container.
No mocking of the DB per ADR-0012.
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
import pytest
from psycopg import errors as pg_errors

from recall.db.schema import ensure_schema

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _table_exists(conn_string: str, table: str) -> bool:
    async with (
        await psycopg.AsyncConnection.connect(conn_string) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return (await cur.fetchone()) is not None


async def _column_names(conn_string: str, table: str) -> set[str]:
    async with (
        await psycopg.AsyncConnection.connect(conn_string) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        return {r[0] for r in await cur.fetchall()}


# ---------------------------------------------------------------------------
# TestEnsureSchema — core contract
# ---------------------------------------------------------------------------


class TestEnsureSchema:
    """Integration tests for ensure_schema."""

    async def test_creates_all_tables(self, pg_conn: str) -> None:
        """Given an empty DB, ensure_schema creates store, store_vectors, projects."""
        await ensure_schema(pg_conn)
        assert await _table_exists(pg_conn, "store")
        assert await _table_exists(pg_conn, "store_vectors")
        assert await _table_exists(pg_conn, "projects")

    async def test_idempotent_second_run(self, pg_conn: str) -> None:
        """Given a fully set-up DB, ensure_schema succeeds with no errors."""
        await ensure_schema(pg_conn)
        await ensure_schema(pg_conn)  # must not raise

    async def test_store_usable_after_setup(self, pg_conn: str) -> None:
        """After ensure_schema, AsyncPostgresStore.aput succeeds."""
        from langgraph.store.postgres import AsyncPostgresStore

        from recall.db.schema import _phase0_index_config

        await ensure_schema(pg_conn)
        async with AsyncPostgresStore.from_conn_string(
            pg_conn, index=_phase0_index_config()
        ) as store:
            await store.aput(
                ("project", "test-proj"),
                "k1",
                {"kind": "decision", "text": "hello"},
                index=False,
            )
            item = await store.aget(("project", "test-proj"), "k1")
        assert item is not None


# ---------------------------------------------------------------------------
# TestScopeConstraint — CHECK on store.prefix
# ---------------------------------------------------------------------------


class TestScopeConstraint:
    """Integration tests for the scope CHECK constraint (ADR-0001/0002)."""

    async def test_global_requires_underscore(self, migrated_db: str) -> None:
        """INSERT with prefix='global.myproj' violates CHECK."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                    ("global.myproj", "k1", "{}"),
                )

    async def test_project_rejects_underscore(self, migrated_db: str) -> None:
        """INSERT with prefix='project._' violates CHECK."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                    ("project._", "k1", "{}"),
                )

    async def test_happy_path_project(self, migrated_db: str) -> None:
        """INSERT with prefix='project.myproj' succeeds."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                ("project.myproj", "k1", "{}"),
            )
            await conn.commit()

    async def test_happy_path_global(self, migrated_db: str) -> None:
        """INSERT with prefix='global._' succeeds."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                ("global._", "k1", "{}"),
            )
            await conn.commit()

    async def test_constraint_exists(self, migrated_db: str) -> None:
        """Named CHECK constraint 'store_scope_invariant' is registered."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name = 'store' "
                "AND constraint_name = 'store_scope_invariant' "
                "AND constraint_type = 'CHECK'"
            )
            assert (await cur.fetchone()) is not None


# ---------------------------------------------------------------------------
# TestProjectsTable — projects table (ADR-0009)
# ---------------------------------------------------------------------------


class TestProjectsTable:
    """Integration tests for the projects table."""

    async def test_projects_table_shape(self, migrated_db: str) -> None:
        """Projects table exists with expected columns."""
        assert await _table_exists(migrated_db, "projects")
        cols = await _column_names(migrated_db, "projects")
        assert {"id", "display_name", "created_at", "created_by"} <= cols

    async def test_global_name_rejected(self, migrated_db: str) -> None:
        """INSERT with id='Global' (any case) violates CHECK."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO projects (id, display_name, created_by) VALUES (%s, %s, %s)",
                    ("Global", "Global project", "operator-1"),
                )

    async def test_valid_project_accepted(self, migrated_db: str) -> None:
        """INSERT with id='my-project' succeeds."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "INSERT INTO projects (id, display_name, created_by) VALUES (%s, %s, %s)",
                ("my-project", "My Project", "operator-1"),
            )
            await conn.commit()


# ---------------------------------------------------------------------------
# TestCliDbMigrate — CLI level
# ---------------------------------------------------------------------------


class TestCliDbMigrate:
    """CLI-level tests for ``recall db migrate``."""

    async def test_exits_zero_on_success(self, pg_conn: str) -> None:
        """`recall db migrate` with DATABASE_URL exits 0."""
        env = dict(os.environ)
        env["DATABASE_URL"] = pg_conn
        result = subprocess.run(  # noqa: ASYNC221
            [sys.executable, "-m", "recall.cli", "db", "migrate"],
            capture_output=True,
            timeout=60,
            env=env,
        )
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert b"up to date" in result.stdout.lower()


# ---------------------------------------------------------------------------
# TestCliServeStartup — auto-migrate hook
# ---------------------------------------------------------------------------


class TestCliServeStartup:
    """`recall serve` auto-migrate on startup."""

    async def test_default_runs_schema_setup(self, pg_conn: str) -> None:
        """Default (flag unset) → schema is set up on startup."""
        env = dict(os.environ)
        env["DATABASE_URL"] = pg_conn
        subprocess.run(  # noqa: ASYNC221
            [sys.executable, "-m", "recall.cli", "serve", "--dry-run"],
            capture_output=True,
            timeout=60,
            env=env,
        )
        assert await _table_exists(pg_conn, "store")
        assert await _table_exists(pg_conn, "projects")

    async def test_false_skips_schema_setup(self, pg_conn: str) -> None:
        """RECALL_DB_MIGRATE_ON_STARTUP=false → schema NOT set up."""
        env = dict(os.environ)
        env["DATABASE_URL"] = pg_conn
        env["RECALL_DB_MIGRATE_ON_STARTUP"] = "false"
        subprocess.run(  # noqa: ASYNC221
            [sys.executable, "-m", "recall.cli", "serve", "--dry-run"],
            capture_output=True,
            timeout=60,
            env=env,
        )
        assert not await _table_exists(pg_conn, "store")
