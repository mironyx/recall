"""Bearer token authentication (ADR-0007)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from recall.errors import UnauthenticatedError


@dataclass(frozen=True)
class AuthConfig:
    """Immutable token-to-user mapping loaded at startup."""

    token_map: dict[str, str]  # token → user_id


def load_auth_config(auth_file_path: str) -> AuthConfig:
    """Load token map from a JSON file.

    File format: {"<token>": {"user_id": "<id>"}, ...}

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not valid JSON or has wrong shape.

    TODO(#91): reading the path from RECALL_AUTH_FILE is wired at server
    startup by E1.6 (Tool Router + MCP wiring); this loader deliberately
    takes an explicit path per LLD §E1.1.
    """
    with open(auth_file_path) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("auth file root must be a JSON object")

    token_map: dict[str, str] = {}
    for token, value in data.items():
        # NOTE: error messages deliberately do not include the token value —
        # it is a live credential (ADR-0007) and must not reach logs.
        if not isinstance(value, dict):
            raise ValueError("auth file entry must be an object with a user_id")
        user_id = value.get("user_id")
        if not isinstance(user_id, str):
            raise ValueError("auth file entry must have a string user_id")
        token_map[token] = user_id
    return AuthConfig(token_map=token_map)


def authenticate(auth_config: AuthConfig, authorization_header: str | None) -> str:
    """Extract and validate the bearer token from the Authorization header.

    Args:
        auth_config: The loaded token map.
        authorization_header: The raw Authorization header value, or None.

    Returns:
        The resolved user_id.

    Raises:
        UnauthenticatedError: if the header is missing, malformed, or the
            token is not in the map.
    """
    if authorization_header is None:
        raise UnauthenticatedError()

    parts = authorization_header.split()
    # RFC 7235 §2.1: auth-scheme tokens are case-insensitive.
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthenticatedError()

    user_id = auth_config.token_map.get(parts[1])
    if user_id is None:
        raise UnauthenticatedError()
    return user_id
