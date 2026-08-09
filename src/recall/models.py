"""Domain models and the flat value schema (ADR-0001)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """The flat value schema stored in AsyncPostgresStore.

    All fields are at the root of the JSONB `value` column.
    This model IS the stored shape — no hoist/unhoist (ADR-0001).
    """

    scope: str  # "project" | "global"
    project_id: str  # project ID or "_" for global
    user_id: str  # who created/last updated
    kind: str  # free-form: decision, convention, etc.
    title: str  # short title
    content: str  # full content
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str  # ISO-8601 UTC
    updated_at: str  # ISO-8601 UTC


class MemoryResponse(BaseModel):
    """Full memory record returned by memory_get."""

    id: str
    scope: str
    project_id: str
    user_id: str
    kind: str
    title: str
    content: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
