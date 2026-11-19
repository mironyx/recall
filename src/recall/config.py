"""Search configuration — injected, never read from the environment in a request path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from recall.errors import ValidationError

# ADR-0010: open interval for the project boost.
_BOOST_MIN, _BOOST_MAX = 0.02, 0.17


@dataclass(frozen=True)
class SearchConfig:
    project_boost: float = 0.05
    default_limit: int = 10
    max_limit: int = 50
    snippet_max_chars: int = 200


def _parse[T: (int, float)](env: Mapping[str, str], name: str, cast: type[T], default: T) -> T:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValidationError(f"{name}={raw!r} is not a valid {cast.__name__}") from None


def load_search_config(env: Mapping[str, str]) -> SearchConfig:
    """Build a SearchConfig from env vars; raises ValidationError naming the variable."""
    d = SearchConfig()
    cfg = SearchConfig(
        project_boost=_parse(env, "RECALL_PROJECT_BOOST", float, d.project_boost),
        default_limit=_parse(env, "RECALL_DEFAULT_LIMIT", int, d.default_limit),
        max_limit=_parse(env, "RECALL_MAX_LIMIT", int, d.max_limit),
        snippet_max_chars=_parse(env, "RECALL_SNIPPET_MAX_CHARS", int, d.snippet_max_chars),
    )
    if not _BOOST_MIN < cfg.project_boost < _BOOST_MAX:
        raise ValidationError(
            f"RECALL_PROJECT_BOOST={cfg.project_boost} outside ADR-0010 bounds "
            f"({_BOOST_MIN}, {_BOOST_MAX})"
        )
    if cfg.default_limit > cfg.max_limit:
        raise ValidationError(
            f"RECALL_DEFAULT_LIMIT={cfg.default_limit} exceeds RECALL_MAX_LIMIT={cfg.max_limit}"
        )
    return cfg
