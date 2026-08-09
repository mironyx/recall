"""Shared error types and structured error formatting."""

from __future__ import annotations

# TODO(#91): Promote ValidationError to the LLD §E1.1 shape —
# RecallError base with error='validation_error' + hint=detail attributes.
# E1.1 (#86) has landed RecallError/UnauthenticatedError in this module;
# the promotion is still deferred because the E1.6 error formatter
# (issue #91, REQ-story-43) is the consumer of the structured shape and a
# bare message is sufficient until then.


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


class ValidationError(Exception):
    """Raised when input fails validation at the API boundary."""


class NotFoundError(RecallError):
    def __init__(self, memory_id: str) -> None:
        super().__init__(
            error="not_found",
            hint=f"Memory '{memory_id}' does not exist. Verify the ID or search first.",
        )
