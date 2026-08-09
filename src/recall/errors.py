"""Shared error types and structured error formatting."""


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
