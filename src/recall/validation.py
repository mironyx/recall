"""Input validation helpers (ADR-0002, ADR-0014)."""

from __future__ import annotations

import re

from recall.errors import ValidationError

PROJECT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
RESERVED_PROJECT_IDS: frozenset[str] = frozenset({"global", "_"})


def validate_project_id_format(project_id: str) -> None:
    """Check project_id matches ^[a-zA-Z0-9_-]{1,128}$ (ADR-0002).

    Also rejects reserved names: 'global', '_' (case-insensitive).

    This is a pure function — no I/O, no DB, no cache. Per ADR-0014,
    any well-formed, non-reserved project_id is accepted on first write.
    No pre-registration required.

    Raises:
        ValidationError: on format violation or reserved name.
    """
    if not project_id:
        raise ValidationError("project_id must not be empty")
    if project_id.lower() in RESERVED_PROJECT_IDS:
        raise ValidationError(
            f"'{project_id}' is a reserved name and cannot be used as a project_id"
        )
    if not PROJECT_ID_PATTERN.match(project_id):
        raise ValidationError(
            f"project_id '{project_id}' is invalid. Must match ^[a-zA-Z0-9_-]{{1,128}}$"
        )
