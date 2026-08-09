"""Unit tests for the Auth component — token-file loader and authenticate() (Issue #86).

Contract sources:
- ``docs/design/v2/lld-e1-one-memory-e2e.md`` §E1.1 (anchor ``LLD-e1-auth``)
  and §E1-errors (anchor ``LLD-e1-errors``)
- ``docs/requirements/v2-requirements.md`` Story 5.6 (bearer token authentication)
- ``docs/adr/0007-shared-bearer-token-auth.md`` (token → user_id map, file format)

These tests are written against the PUBLIC API only: ``AuthConfig``,
``load_auth_config``, ``authenticate``, ``UnauthenticatedError``. No database
or integration marker is needed — the Auth contract is pure (LLD: "pure
function — no I/O, no DB").
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from recall.auth import AuthConfig, authenticate, load_auth_config
from recall.errors import RecallError, UnauthenticatedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_auth_file(tmp_path: Path, token_map: dict[str, dict[str, str]]) -> Path:
    """Write a JSON auth file of the format {"<token>": {"user_id": "<id>"}}."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(token_map))
    return auth_file


class TestAuth:
    """Unit tests for the Auth component (Issue #86, LLD §BDD ``TestAuth``)."""

    # ------------------------------------------------------------------
    # authenticate() — token resolution
    # ------------------------------------------------------------------

    def test_valid_token_resolves_user_id(self) -> None:
        """Given a token in the auth map, authenticate returns user_id.

        Story 5.6 AC2: auth file contains ``{"tok_abc": {"user_id": "alice"}}``,
        request arrives with ``Authorization: Bearer tok_abc``, the request
        proceeds with ``user_id=alice``.
        """
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        assert authenticate(cfg, "Bearer tok_abc") == "alice"

    def test_each_token_resolves_its_own_user(self) -> None:
        """Given multiple tokens in the map, each bearer token resolves to its
        own configured user_id."""
        cfg = AuthConfig(token_map={"tok_abc": "alice", "tok_xyz": "bob"})
        assert authenticate(cfg, "Bearer tok_abc") == "alice"
        assert authenticate(cfg, "Bearer tok_xyz") == "bob"

    def test_empty_token_map_rejects_all_requests(self) -> None:
        """Given an auth map with no tokens, any bearer header is rejected."""
        cfg = AuthConfig(token_map={})
        with pytest.raises(UnauthenticatedError):
            authenticate(cfg, "Bearer tok_abc")

    # ------------------------------------------------------------------
    # authenticate() — rejection paths (missing / unknown / malformed)
    # ------------------------------------------------------------------

    def test_missing_token_raises(self) -> None:
        """Given no Authorization header (None), authenticate raises
        UnauthenticatedError (Story 5.6 AC3)."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        with pytest.raises(UnauthenticatedError) as excinfo:
            authenticate(cfg, None)
        err = excinfo.value
        assert err.error == "unauthenticated"
        assert isinstance(err.hint, str) and err.hint

    def test_unknown_token_raises(self) -> None:
        """Given an unrecognised token, authenticate raises UnauthenticatedError
        with the same structured {error, hint} shape (Story 5.6 AC4)."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        with pytest.raises(UnauthenticatedError) as excinfo:
            authenticate(cfg, "Bearer nope")
        err = excinfo.value
        assert err.error == "unauthenticated"
        assert isinstance(err.hint, str) and err.hint

    @pytest.mark.parametrize(
        "header",
        [
            "Basic abc123",  # wrong scheme
            "Token tok_abc",  # wrong scheme
            "Digest realm=recall",
            "Bearer",  # scheme without a token
        ],
    )
    def test_malformed_header_raises(self, header: str) -> None:
        """Given an Authorization header that is not "Bearer <token>",
        authenticate raises UnauthenticatedError."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        with pytest.raises(UnauthenticatedError):
            authenticate(cfg, header)

    def test_bearer_prefix_with_empty_token_raises(self) -> None:
        """Given a header of "Bearer " with an empty token, authenticate
        raises UnauthenticatedError (edge of the malformed set)."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        with pytest.raises(UnauthenticatedError):
            authenticate(cfg, "Bearer ")

    @pytest.mark.parametrize("header", ["bearer tok_abc", "BEARER tok_abc", "BeArEr tok_abc"])
    def test_bearer_scheme_is_case_insensitive(self, header: str) -> None:
        """Given a valid token under any letter case of the "Bearer" scheme,
        authenticate resolves the user_id (RFC 7235 §2.1 — auth-scheme tokens
        are case-insensitive). Regression test for PR #112 review finding."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        assert authenticate(cfg, header) == "alice"

    # ------------------------------------------------------------------
    # load_auth_config() — token-file parsing (Story 5.6 AC1)
    # ------------------------------------------------------------------

    def test_auth_file_loaded_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Given RECALL_AUTH_FILE pointing to a JSON file, the auth map is
        loaded at startup (issue #86 BDD spec test)."""
        auth_file = _write_auth_file(tmp_path, {"tok_abc": {"user_id": "alice"}})
        monkeypatch.setenv("RECALL_AUTH_FILE", str(auth_file))
        cfg = load_auth_config(os.environ["RECALL_AUTH_FILE"])
        assert cfg.token_map == {"tok_abc": "alice"}

    def test_load_parses_token_to_user_map(self, tmp_path: Path) -> None:
        """Given a file of the format {"<token>": {"user_id": "<id>"}}, the
        token_map is parsed as token → user_id (ADR-0007 file format)."""
        auth_file = _write_auth_file(
            tmp_path, {"tok_abc": {"user_id": "alice"}, "tok_xyz": {"user_id": "bob"}}
        )
        cfg = load_auth_config(str(auth_file))
        assert cfg.token_map == {"tok_abc": "alice", "tok_xyz": "bob"}
        assert cfg == AuthConfig(token_map={"tok_abc": "alice", "tok_xyz": "bob"})

    def test_load_empty_auth_file(self, tmp_path: Path) -> None:
        """Given an empty JSON object, load succeeds with an empty token_map."""
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("{}")
        cfg = load_auth_config(str(auth_file))
        assert cfg.token_map == {}

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        """Given a non-existent auth file path, load_auth_config raises
        FileNotFoundError."""
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(FileNotFoundError):
            load_auth_config(str(missing))

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        """Given a file that is not valid JSON, load_auth_config raises
        ValueError."""
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("{not valid json")
        with pytest.raises(ValueError):
            load_auth_config(str(auth_file))

    @pytest.mark.parametrize("content", ["[]", '"tok_abc"', "42"])
    def test_load_non_dict_root_raises(self, tmp_path: Path, content: str) -> None:
        """Given a JSON document whose root is not an object, load_auth_config
        raises ValueError."""
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(content)
        with pytest.raises(ValueError):
            load_auth_config(str(auth_file))

    @pytest.mark.parametrize(
        "content",
        [
            '{"tok_abc": "alice"}',  # token value is not an object
            '{"tok_abc": {}}',  # token value object without user_id
            '{"tok_abc": null}',  # token value is null
        ],
    )
    def test_load_token_value_without_user_id_raises(self, tmp_path: Path, content: str) -> None:
        """Given a token whose value is not an object with a user_id key,
        load_auth_config raises ValueError."""
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(content)
        with pytest.raises(ValueError):
            load_auth_config(str(auth_file))

    @pytest.mark.parametrize(
        "content",
        [
            '{"tok_abc": {"user_id": 42}}',  # user_id is a number
            '{"tok_abc": {"user_id": null}}',  # user_id is null
            '{"tok_abc": {"user_id": ["alice"]}}',  # user_id is a list
        ],
    )
    def test_load_user_id_must_be_string(self, tmp_path: Path, content: str) -> None:
        """Given a token entry whose user_id value is not a string, load_auth_config
        raises ValueError (LLD §E1.1: "ValueError: if the file is not valid JSON
        or has wrong shape" — the file format is {"<token>": {"user_id": "<id>"}}).

        Without this check a valid token resolves to a non-str value, silently
        violating authenticate()'s documented ``-> str`` contract and corrupting
        user_id downstream (stored memories, audit logs).
        """
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(content)
        with pytest.raises(ValueError):
            load_auth_config(str(auth_file))

    def test_reload_reads_updated_file(self, tmp_path: Path) -> None:
        """Given the auth file is updated and load_auth_config runs again
        (server restart semantics, Story 5.6 AC5 — no hot reload in v2 per
        ADR-0007), the new token map takes effect."""
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps({"tok_abc": {"user_id": "alice"}}))
        assert load_auth_config(str(auth_file)).token_map == {"tok_abc": "alice"}
        auth_file.write_text(json.dumps({"tok_new": {"user_id": "bob"}}))
        assert load_auth_config(str(auth_file)).token_map == {"tok_new": "bob"}

    # ------------------------------------------------------------------
    # Error contract, immutability, purity
    # ------------------------------------------------------------------

    def test_unauthenticated_error_shape(self) -> None:
        """UnauthenticatedError carries the {error, hint} envelope — error is
        "unauthenticated" and hint is a non-empty string (LLD §E1-errors)."""
        err = UnauthenticatedError()
        assert isinstance(err, RecallError)
        assert err.error == "unauthenticated"
        assert isinstance(err.hint, str) and err.hint
        assert str(err) == "unauthenticated"

    def test_authenticate_does_not_mutate_config(self) -> None:
        """authenticate is a pure function — it must not mutate the AuthConfig
        on either the happy path or the rejection path."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        before = dict(cfg.token_map)

        assert authenticate(cfg, "Bearer tok_abc") == "alice"
        assert cfg.token_map == before

        with pytest.raises(UnauthenticatedError):
            authenticate(cfg, "Bearer nope")
        assert cfg.token_map == before

    def test_auth_config_is_frozen(self) -> None:
        """AuthConfig is an immutable (frozen) dataclass — mutating token_map
        raises FrozenInstanceError."""
        cfg = AuthConfig(token_map={"tok_abc": "alice"})
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.token_map = {}  # type: ignore[misc]  # frozen dataclass: read-only by design
