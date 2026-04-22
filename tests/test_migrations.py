"""Integration tests for the migration runner and initial schema.

Covers issue #76 (E0.4). Exercises the real ``apply_pending`` function against
a real Postgres+pgvector container — no mocking of the DB per ADR-0012.

Test groups
-----------
* ``TestApplyPending`` — runner contract (I1-I3, I6, AC1-AC4)
* ``TestInitialMigration`` — 0001_initial.sql (I4, I6, AC5)
* ``TestProjectsMigration`` — 0002_projects.sql (I5, AC6)
* ``TestCliDbMigrate`` — ``recall db migrate`` CLI (AC7)
* ``TestCliServeStartup`` — ``recall serve`` auto-migrate hook (AC8)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as pg_errors

from recall.db import migrations as mig_module
from recall.db.migrations import apply_pending

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_EXPECTED_VERSIONS = ("0001_initial", "0002_projects")

_REAL_MIGRATIONS_DIR: Path = Path(mig_module.__file__).resolve().parent.parent / "migrations"


async def _fetch_applied_versions(conn_string: str) -> list[str]:
    """Return the ordered list of versions recorded in ``schema_migrations``."""
    async with (
        await psycopg.AsyncConnection.connect(conn_string) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        rows = await cur.fetchall()
    return [r[0] for r in rows]


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
# TestApplyPending — runner contract
# ---------------------------------------------------------------------------


class TestApplyPending:
    """Integration tests for the migration runner."""

    async def test_applies_all_pending_migrations(self, pg_conn: str) -> None:
        """Given an empty DB, apply_pending runs all migrations in filename order."""
        applied = await apply_pending(pg_conn)

        # Returns the full list of versions in filename order.
        assert applied == list(_EXPECTED_VERSIONS)

        # And each version is now recorded in schema_migrations.
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_idempotent_second_run(self, pg_conn: str) -> None:
        """Given a fully migrated DB, apply_pending returns an empty list (I1)."""
        first = await apply_pending(pg_conn)
        assert first == list(_EXPECTED_VERSIONS)

        second = await apply_pending(pg_conn)
        assert second == []

        # schema_migrations has exactly one row per version (no duplicates).
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_partial_failure_rolls_back(
        self,
        pg_conn: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Given a migration that raises, schema_migrations has no entry for it (I3)."""
        # Build a synthetic migrations directory: a valid 0001 and a broken 0002.
        # Small synchronous filesystem setup is fine in a test — ASYNC240 noise.
        fake_dir = tmp_path / "migrations"
        fake_dir.mkdir()
        real_0001_text = (_REAL_MIGRATIONS_DIR / "0001_initial.sql").read_text()
        (fake_dir / "0001_initial.sql").write_text(real_0001_text)
        (fake_dir / "0002_bad.sql").write_text("CREATE TABLE broken_migration (x INVALID_TYPE);\n")

        monkeypatch.setattr(mig_module, "MIGRATIONS_DIR", fake_dir)

        with pytest.raises(Exception):  # noqa: B017 — DBAPI error class is an implementation detail
            await apply_pending(pg_conn)

        recorded = await _fetch_applied_versions(pg_conn)
        # 0001 committed successfully; 0002_bad rolled back and NOT recorded.
        assert "0001_initial" in recorded
        assert "0002_bad" not in recorded
        # The bad migration left no table behind.
        assert not await _table_exists(pg_conn, "broken_migration")

    async def test_concurrent_calls_serialise(self, pg_conn: str) -> None:
        """Two concurrent apply_pending calls — every migration applied exactly once (I2)."""
        results = await asyncio.gather(
            apply_pending(pg_conn),
            apply_pending(pg_conn),
            return_exceptions=True,
        )

        # Neither call raised.
        for r in results:
            assert not isinstance(r, BaseException), f"concurrent call raised: {r!r}"

        # Union of both return values covers every version, with no version reported twice.
        r0, r1 = results
        assert isinstance(r0, list)
        assert isinstance(r1, list)
        union = r0 + r1
        assert sorted(union) == sorted(_EXPECTED_VERSIONS)

        # Ledger has exactly one row per migration.
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_schema_migrations_table_shape(self, pg_conn: str) -> None:
        """schema_migrations has the expected (version, applied_at) columns (ADR-0013)."""
        await apply_pending(pg_conn)
        cols = await _column_names(pg_conn, "schema_migrations")
        assert "version" in cols
        assert "applied_at" in cols


# ---------------------------------------------------------------------------
# TestInitialMigration — 0001_initial.sql
# ---------------------------------------------------------------------------


class TestInitialMigration:
    """Integration tests for 0001_initial.sql (I4, I6)."""

    async def test_store_tables_created(self, migrated_db: str) -> None:
        """After 0001, the store and store_vectors tables exist (I6)."""
        assert await _table_exists(migrated_db, "store")
        assert await _table_exists(migrated_db, "store_vectors")

    async def test_scope_check_global_requires_underscore(self, migrated_db: str) -> None:
        """INSERT with scope='global', project_id='myproj' violates CHECK (I4)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                    ("global.myproj", "k1", "{}"),
                )

    async def test_scope_check_project_rejects_underscore(self, migrated_db: str) -> None:
        """INSERT with scope='project', project_id='_' violates CHECK (I4)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                    ("project._", "k1", "{}"),
                )

    async def test_scope_check_happy_path_project(self, migrated_db: str) -> None:
        """INSERT with scope='project', project_id='myproj' succeeds (I4 happy path)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                ("project.myproj", "k1", "{}"),
            )
            await conn.commit()

    async def test_scope_check_happy_path_global(self, migrated_db: str) -> None:
        """INSERT with scope='global', project_id='_' (sentinel) succeeds (I4 happy path)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "INSERT INTO store (prefix, key, value) VALUES (%s, %s, %s::jsonb)",
                ("global._", "k1", "{}"),
            )
            await conn.commit()

    async def test_store_scope_invariant_constraint_exists(self, migrated_db: str) -> None:
        """Named CHECK constraint 'store_scope_invariant' is registered on the store table."""
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
            row = await cur.fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# TestProjectsMigration — 0002_projects.sql
# ---------------------------------------------------------------------------


class TestProjectsMigration:
    """Integration tests for 0002_projects.sql (I5)."""

    async def test_projects_table_created(self, migrated_db: str) -> None:
        """After 0002, the projects table exists with the expected columns."""
        assert await _table_exists(migrated_db, "projects")
        cols = await _column_names(migrated_db, "projects")
        assert {"id", "display_name", "created_at", "created_by"} <= cols

    async def test_projects_primary_key_is_id(self, migrated_db: str) -> None:
        """id is the PRIMARY KEY of the projects table."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT a.attname "
                "FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'projects'::regclass AND i.indisprimary"
            )
            rows = await cur.fetchall()
        assert [r[0] for r in rows] == ["id"]

    async def test_global_name_rejected_lower(self, migrated_db: str) -> None:
        """INSERT with id='global' violates CHECK (I5)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO projects (id, display_name, created_by) VALUES (%s, %s, %s)",
                    ("global", "Global project", "operator-1"),
                )

    async def test_global_name_rejected_capitalised(self, migrated_db: str) -> None:
        """INSERT with id='Global' violates CHECK — case-insensitive via lower() (I5)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO projects (id, display_name, created_by) VALUES (%s, %s, %s)",
                    ("Global", "Global project", "operator-1"),
                )

    async def test_global_name_rejected_upper(self, migrated_db: str) -> None:
        """INSERT with id='GLOBAL' violates CHECK — case-insensitive via lower() (I5)."""
        async with (
            await psycopg.AsyncConnection.connect(migrated_db) as conn,
            conn.cursor() as cur,
        ):
            with pytest.raises(pg_errors.CheckViolation):
                await cur.execute(
                    "INSERT INTO projects (id, display_name, created_by) VALUES (%s, %s, %s)",
                    ("GLOBAL", "Global project", "operator-1"),
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
            await cur.execute("SELECT id FROM projects WHERE id = 'my-project'")
            row = await cur.fetchone()
            await conn.commit()
        assert row == ("my-project",)


# ---------------------------------------------------------------------------
# TestCliDbMigrate — `recall db migrate`
# ---------------------------------------------------------------------------


def _run_cli(
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m recall.cli <args>``. ``env`` merges over the parent process env."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "recall.cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged,
    )


class TestCliDbMigrate:
    """CLI-level tests for ``recall db migrate`` (AC7)."""

    async def test_db_migrate_reads_database_url_and_exits_zero(self, pg_conn: str) -> None:
        """`recall db migrate` reads DATABASE_URL, applies migrations, exits 0."""
        result = _run_cli("db", "migrate", env={"DATABASE_URL": pg_conn})
        assert result.returncode == 0, f"stderr={result.stderr!r} stdout={result.stdout!r}"
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_db_migrate_prints_applied_versions(self, pg_conn: str) -> None:
        """stdout mentions each applied version (0001_initial, 0002_projects)."""
        result = _run_cli("db", "migrate", env={"DATABASE_URL": pg_conn})
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        for version in _EXPECTED_VERSIONS:
            assert version in combined, f"{version!r} not in CLI output: {combined!r}"

    async def test_db_migrate_idempotent_second_invocation(self, pg_conn: str) -> None:
        """Second `recall db migrate` invocation exits 0 even when nothing is pending."""
        first = _run_cli("db", "migrate", env={"DATABASE_URL": pg_conn})
        assert first.returncode == 0
        second = _run_cli("db", "migrate", env={"DATABASE_URL": pg_conn})
        assert second.returncode == 0

    def test_db_migrate_fails_without_database_url(self) -> None:
        """With no DATABASE_URL in the environment, `recall db migrate` exits non-zero."""
        result = subprocess.run(
            [sys.executable, "-m", "recall.cli", "db", "migrate"],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": os.environ.get("PATH", "")},
        )
        assert result.returncode != 0

    def test_db_migrate_fails_on_bad_url(self) -> None:
        """Given an unreachable DATABASE_URL, `recall db migrate` exits 1, not 0."""
        result = _run_cli(
            "db",
            "migrate",
            env={"DATABASE_URL": "postgresql://nobody:nothing@127.0.0.1:1/doesnotexist"},
            timeout=30,
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# TestCliServeStartup — `recall serve` auto-migrate hook
# ---------------------------------------------------------------------------


class TestCliServeStartup:
    """`recall serve` runs apply_pending on startup, gated by RECALL_DB_MIGRATE_ON_STARTUP."""

    async def test_serve_default_runs_migrations_on_startup(self, pg_conn: str) -> None:
        """Default (unset flag) → migrations run on `recall serve` startup (AC8)."""
        # `recall serve` is a Phase-0 stub; whatever it does, it must apply pending
        # migrations first when the flag is unset (= default "true"). We accept any
        # exit code — the observable property is that the schema is migrated.
        _run_cli("serve", env={"DATABASE_URL": pg_conn}, timeout=60)

        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_serve_explicit_true_runs_migrations(self, pg_conn: str) -> None:
        """RECALL_DB_MIGRATE_ON_STARTUP=true → migrations run on startup (AC8)."""
        _run_cli(
            "serve",
            env={
                "DATABASE_URL": pg_conn,
                "RECALL_DB_MIGRATE_ON_STARTUP": "true",
            },
            timeout=60,
        )
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == list(_EXPECTED_VERSIONS)

    async def test_serve_false_skips_migrations(self, pg_conn: str) -> None:
        """RECALL_DB_MIGRATE_ON_STARTUP=false → migrations NOT run on startup."""
        _run_cli(
            "serve",
            env={
                "DATABASE_URL": pg_conn,
                "RECALL_DB_MIGRATE_ON_STARTUP": "false",
            },
            timeout=60,
        )
        assert not await _table_exists(pg_conn, "schema_migrations")
