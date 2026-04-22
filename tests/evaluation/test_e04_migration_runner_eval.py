"""Adversarial evaluation tests for Issue #76 — E0.4 Migration runner and initial schema.

Probes three gaps not covered by tests/test_migrations.py:

1. RECALL_DB_MIGRATE_ON_STARTUP falsy-value variants "0", "no", "off" — the
   implementation lists all three in _FALSY_ENV_VALUES but the existing tests
   only exercise "false". A regression that drops one variant would go unnoticed.

2. Advisory-lock release after a failed migration run — the finally block in
   apply_pending calls pg_advisory_unlock, but no test verifies that a
   subsequent apply_pending call succeeds after a prior one raised. If the lock
   leaked, the second call would block indefinitely (or until session close).

3. Selective application of a new migration when earlier ones are already
   applied — verifies that apply_pending skips versions present in
   schema_migrations and only runs the genuinely pending file, returning just
   the new version string.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Import helpers from the feature's own test module to avoid duplication.
# ---------------------------------------------------------------------------

from tests.test_migrations import (  # noqa: E402
    _REAL_MIGRATIONS_DIR,
    _fetch_applied_versions,
    _run_cli,
    _table_exists,
)

import recall.db.migrations as mig_module  # noqa: E402
from recall.db.migrations import apply_pending  # noqa: E402

# ---------------------------------------------------------------------------
# 1. RECALL_DB_MIGRATE_ON_STARTUP falsy-value variants
# ---------------------------------------------------------------------------


class TestMigrateOnStartupFalsyVariants:
    """All standard falsy env strings should suppress migration on serve startup."""

    @pytest.mark.parametrize("falsy_value", ["0", "no", "off"])
    async def test_serve_falsy_variant_skips_migrations(
        self, pg_conn: str, falsy_value: str
    ) -> None:
        """RECALL_DB_MIGRATE_ON_STARTUP=<falsy> → migrations NOT run; schema_migrations absent."""
        _run_cli(
            "serve",
            env={
                "DATABASE_URL": pg_conn,
                "RECALL_DB_MIGRATE_ON_STARTUP": falsy_value,
            },
            timeout=60,
        )
        # schema_migrations must NOT exist — migrations were skipped.
        absent = not await _table_exists(pg_conn, "schema_migrations")
        assert absent, (
            f"RECALL_DB_MIGRATE_ON_STARTUP={falsy_value!r} should suppress migrations "
            "but schema_migrations was found"
        )


# ---------------------------------------------------------------------------
# 2. Advisory-lock released on exception — second call proceeds
# ---------------------------------------------------------------------------


class TestAdvisoryLockReleasedOnFailure:
    """A failed apply_pending call must release the advisory lock so the next call can proceed."""

    async def test_second_call_succeeds_after_failure(
        self,
        pg_conn: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """apply_pending with a broken migration raises, then a second call with a good
        migrations dir completes successfully — proving the lock was not leaked."""
        # Build a synthetic dir with a bad 0001.
        bad_dir = tmp_path / "migrations_bad"
        bad_dir.mkdir()
        (bad_dir / "0001_bad.sql").write_text("INVALID SQL THAT WILL FAIL;\n")

        monkeypatch.setattr(mig_module, "MIGRATIONS_DIR", bad_dir)
        with pytest.raises(Exception):  # noqa: B017 — DBAPI error class is an implementation detail
            await apply_pending(pg_conn)

        # Now switch to the real migrations dir and run again.
        monkeypatch.setattr(mig_module, "MIGRATIONS_DIR", _REAL_MIGRATIONS_DIR)
        applied = await apply_pending(pg_conn)

        # If the lock leaked the call would hang; reaching here proves it didn't.
        assert "0001_initial" in applied
        assert "0002_projects" in applied


# ---------------------------------------------------------------------------
# 3. Selective application when earlier migrations are already applied
# ---------------------------------------------------------------------------


class TestSelectiveApplication:
    """apply_pending skips already-applied versions and only runs new ones."""

    async def test_only_new_migration_applied(
        self,
        pg_conn: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With 0001/0002 applied, adding a 0003 file causes only 0003 to be applied."""
        # First, apply real migrations so 0001 and 0002 are recorded.
        monkeypatch.setattr(mig_module, "MIGRATIONS_DIR", _REAL_MIGRATIONS_DIR)
        first = await apply_pending(pg_conn)
        assert first == ["0001_initial", "0002_projects"]

        # Now build a synthetic dir that has the real migrations PLUS a 0003.
        extended_dir = tmp_path / "migrations_extended"
        extended_dir.mkdir()
        for name in ("0001_initial.sql", "0002_projects.sql"):
            src = _REAL_MIGRATIONS_DIR / name
            (extended_dir / name).write_text(src.read_text())
        # 0003 creates a trivial table that is safe and idempotent.
        (extended_dir / "0003_extra.sql").write_text(
            "CREATE TABLE IF NOT EXISTS eval_extra (id serial PRIMARY KEY);\n"
        )

        monkeypatch.setattr(mig_module, "MIGRATIONS_DIR", extended_dir)
        second = await apply_pending(pg_conn)

        # Only 0003 should be returned; 0001/0002 were already applied.
        assert second == ["0003_extra"], f"unexpected applied list: {second!r}"

        # All three are now recorded.
        recorded = await _fetch_applied_versions(pg_conn)
        assert recorded == ["0001_initial", "0002_projects", "0003_extra"]
