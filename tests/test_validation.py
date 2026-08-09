"""Tests for Issue #87 — E1.2: Project ID validation — format check, reserved-name guard.

Contract is derived from:

- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.2 (LLD-e1-project-id-validation,
  invariant I9, ``TestProjectIdValidation`` BDD spec)
- ``docs/requirements/v2-requirements.md`` — Story 1.2 (scope invariant),
  Story 5.5 (global-name rejection, case-insensitive)
- ADR-0002 (namespace: sentinel ``"_"`` reserved), ADR-0014 (no registry — any
  well-formed project_id is accepted on first write)

The unit under test is ``recall.validation.validate_project_id_format`` — a pure
function (no I/O, no DB, no cache). All tests are plain unit tests, no
integration marker, no fixtures.
"""

from __future__ import annotations

import re

import pytest

from recall.errors import ValidationError
from recall.validation import RESERVED_PROJECT_IDS, validate_project_id_format


class TestProjectIdValidation:
    """Unit tests for project_id format validation (ADR-0014, LLD I9)."""

    # ------------------------------------------------------------------
    # Valid IDs — must pass with no exception (issue AC: valid IDs pass)
    # ------------------------------------------------------------------

    def test_valid_project_id_accepted(self) -> None:
        """Given a well-formed project_id matching ^[a-zA-Z0-9_-]{1,128}$,
        validation passes (no exception)."""
        for project_id in ("my-project", "alpha_2026", "X9-Y_abc", "MyProject", "123"):
            validate_project_id_format(project_id)

    def test_single_char_project_id_accepted(self) -> None:
        """Given a 1-character project_id (lower bound of {1,128}),
        validation passes."""
        validate_project_id_format("a")

    def test_max_length_project_id_accepted(self) -> None:
        """Given a project_id of exactly 128 characters (upper bound of
        {1,128}), validation passes."""
        validate_project_id_format("p" * 128)

    def test_reserved_lookalike_prefix_accepted(self) -> None:
        """Given a project_id that merely starts with a reserved name
        ('global-prod') or contains the sentinel ('_index'), validation passes —
        the reserved check is exact-match on the whole string, not a prefix."""
        for project_id in ("global-prod", "GLOBAL-prod", "_index"):
            validate_project_id_format(project_id)

    # ------------------------------------------------------------------
    # Reserved names — rejected case-insensitively (issue AC, Story 5.5)
    # ------------------------------------------------------------------

    def test_global_reserved_name_rejected(self) -> None:
        """Given project_id='global' in any case variation, validation raises
        ValidationError (case-insensitive reserved-name check)."""
        for project_id in ("global", "Global", "GLOBAL", "gLoBaL"):
            # re.escape: project_id may contain regex metacharacters (e.g. '?').
            with pytest.raises(ValidationError, match=re.escape(project_id)):
                validate_project_id_format(project_id)

    def test_underscore_sentinel_rejected(self) -> None:
        """Given project_id='_' (the global namespace sentinel, ADR-0002),
        validation raises ValidationError."""
        with pytest.raises(ValidationError, match="_"):
            validate_project_id_format("_")

    # ------------------------------------------------------------------
    # Format violations — rejected (issue AC: invalid characters, too long)
    # ------------------------------------------------------------------

    def test_empty_project_id_rejected(self) -> None:
        """Given an empty project_id, validation raises ValidationError
        ({1,128} requires at least one character)."""
        with pytest.raises(ValidationError):
            validate_project_id_format("")

    def test_special_chars_rejected(self) -> None:
        """Given project_id with dots, spaces, slashes, or other characters
        outside [a-zA-Z0-9_-], validation raises ValidationError."""
        for project_id in (
            "my.project",
            "my project",
            "my/project",
            "my?project",
            "my@project",
            "café",
            "プロジェクト",
            "   ",
            "trailing ",
            " leading",
        ):
            # re.escape: project_id may contain regex metacharacters (e.g. '?').
            with pytest.raises(ValidationError, match=re.escape(project_id)):
                validate_project_id_format(project_id)

    def test_too_long_project_id_rejected(self) -> None:
        """Given project_id longer than 128 characters, validation raises
        ValidationError (upper bound of {1,128} exceeded)."""
        with pytest.raises(ValidationError):
            validate_project_id_format("p" * 129)

    def test_trailing_newline_rejected(self) -> None:
        """Given project_id with a trailing newline, validation raises
        ValidationError (PR review finding: re.match '$' accepts a final
        '\\n', silently bypassing the length bound and reserved-name guard)."""
        for project_id in ("abc\n", "global\n", "GLOBAL\n", "p" * 128 + "\n"):
            with pytest.raises(ValidationError):
                validate_project_id_format(project_id)

    # ------------------------------------------------------------------
    # Error shape — public error type and message contract (Story 4.3)
    # ------------------------------------------------------------------

    def test_raises_shared_validation_error_type(self) -> None:
        """Given any violation, the raised error is the shared
        ``recall.errors.ValidationError`` (the API-boundary error type), not a
        bare ValueError."""
        for project_id in ("", "bad.id", "GLOBAL", "_"):
            with pytest.raises(ValidationError):
                validate_project_id_format(project_id)

    def test_reserved_ids_constant_public_contract(self) -> None:
        """The reserved-name set is part of the module's public surface and
        contains exactly the two reserved values from ADR-0002."""
        assert frozenset({"global", "_"}) == RESERVED_PROJECT_IDS
