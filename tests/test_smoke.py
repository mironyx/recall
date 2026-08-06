"""Smoke integration test — Phase 0 exit criterion (Issue #77).

Exercises the full stack: testcontainers Postgres+pgvector, schema migration,
StubEmbeddingsProvider, and per-test TRUNCATE isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from langgraph.store.postgres import AsyncPostgresStore


@pytest.mark.integration
class TestTestFixture:
    """Integration tests proving the session-scoped fixture itself works."""

    async def test_container_boots_and_schema_applies(self, pg_conn_string: str) -> None:
        """The session fixture delivers a conn_string to a running Postgres
        with all migrations applied."""
        import psycopg

        async with (
            await psycopg.AsyncConnection.connect(pg_conn_string) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'store'"
            )
            assert (await cur.fetchone()) is not None

    async def test_truncate_isolation(self, store: AsyncPostgresStore) -> None:
        """Data inserted in one test is not visible in the next. We insert
        here; a sibling test asserts the table is empty."""
        await store.aput(
            ("project", "test-proj"),
            "k1",
            {"kind": "episode", "text": "data from isolation test"},
            index=False,
        )
        item = await store.aget(("project", "test-proj"), "k1")
        assert item is not None

    async def test_truncate_isolation_no_leak(self, store: AsyncPostgresStore) -> None:
        """The table is empty at test start because the previous test's data
        was truncated."""
        item = await store.aget(("project", "test-proj"), "k1")
        assert item is None


@pytest.mark.integration
class TestSmoke:
    """Smoke integration test — full stack round-trip."""

    async def test_insert_and_read_back(self, store: AsyncPostgresStore) -> None:
        """aput then aget round-trips a memory record."""
        await store.aput(
            ("project", "test-proj"),
            "k2",
            {"kind": "decision", "text": "use testcontainers for integration tests"},
            index=False,
        )
        item = await store.aget(("project", "test-proj"), "k2")
        assert item is not None
        assert item.value == {
            "kind": "decision",
            "text": "use testcontainers for integration tests",
        }

    async def test_scope_check_enforced(self, store: AsyncPostgresStore) -> None:
        """The scope CHECK constraint rejects invalid (scope, project_id)
        combinations."""
        with pytest.raises(Exception) as exc_info:
            await store.aput(
                ("global", "myproj"),
                "bad-key",
                {"kind": "note", "text": "should fail"},
                index=False,
            )
        err_msg = str(exc_info.value).lower()
        assert "check" in err_msg or "constraint" in err_msg or "violation" in err_msg
