"""Shared error types and structured error formatting."""

from __future__ import annotations

# TODO(#91): Promote ValidationError to the LLD §E1.1 shape —
# RecallError base with error='validation_error' + hint=detail attributes,
# once E1.1 (#86) lands RecallError/UnauthenticatedError in this module.
# Deferred — the E1.6 error formatter (issue #91, REQ-story-43) is the
# consumer of the structured shape; a bare message is sufficient today.


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
