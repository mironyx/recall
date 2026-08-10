"""Shared error types and structured error formatting."""

from __future__ import annotations


class RecallError(Exception):
    """Base error for all Recall domain errors."""

    def __init__(self, error: str, hint: str) -> None:
        self.error = error
        self.hint = hint
        super().__init__(error)


class UnauthenticatedError(RecallError):
    def __init__(self) -> None:
        super().__init__(
            error="unauthenticated",
            hint="Provide Authorization: Bearer <token> header.",
        )


class ValidationError(RecallError):
    """Raised when input fails validation at the API boundary.

    Promoted to the RecallError hierarchy (LLD §E1.1 shape) by issue #91 —
    the E1.6 error formatter catches RecallError and needs the structured
    {error, hint} attributes. ``str()`` keeps returning the detail message
    (not the error code) so existing callers that match on the message
    keep working.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(error="validation_error", hint=detail)

    def __str__(self) -> str:
        return self.hint


class NotFoundError(RecallError):
    def __init__(self, memory_id: str) -> None:
        super().__init__(
            error="not_found",
            hint=f"Memory '{memory_id}' does not exist. Verify the ID or search first.",
        )
