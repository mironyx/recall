"""Unit tests for ``recall.config.load_search_config`` (REC-4, E2.2).

Contract: ``docs/design/v2/lld-e2-search.md`` §2.2 (anchor LLD-e2-service-search),
"Config knobs" table; ADR-0010 boost bounds ``(0.02, 0.17)``.

Pure unit tests: the env is passed as a plain dict — no monkeypatching, no reload.
"""

from __future__ import annotations

import pytest

from recall.config import SearchConfig, load_search_config
from recall.errors import ValidationError


class TestLoadSearchConfig:
    """Pure unit tests — env passed as a dict, no monkeypatching, no reload."""

    def test_defaults(self) -> None:
        """Given an empty env, documented defaults are returned (REC-4)."""
        config = load_search_config({})

        assert config == SearchConfig(
            project_boost=0.05, default_limit=10, max_limit=50, snippet_max_chars=200
        )
        assert config.project_boost == 0.05
        assert config.default_limit == 10
        assert config.max_limit == 50
        assert config.snippet_max_chars == 200

    def test_overrides_parsed(self) -> None:
        """Given RECALL_PROJECT_BOOST='0.08' (and the other knobs), the values are
        parsed to their typed fields (REC-4)."""
        config = load_search_config(
            {
                "RECALL_PROJECT_BOOST": "0.08",
                "RECALL_DEFAULT_LIMIT": "7",
                "RECALL_MAX_LIMIT": "30",
                "RECALL_SNIPPET_MAX_CHARS": "120",
            }
        )

        assert config.project_boost == 0.08
        assert config.default_limit == 7
        assert config.max_limit == 30
        assert config.snippet_max_chars == 120

    def test_unrelated_env_vars_ignored(self) -> None:
        """Given an env with unrelated variables, defaults still apply (REC-4)."""
        assert load_search_config({"PATH": "/usr/bin", "DATABASE_URL": "x"}) == SearchConfig()

    @pytest.mark.parametrize(
        "variable",
        [
            "RECALL_PROJECT_BOOST",
            "RECALL_DEFAULT_LIMIT",
            "RECALL_MAX_LIMIT",
            "RECALL_SNIPPET_MAX_CHARS",
        ],
    )
    def test_unparseable_value_raises_naming_the_variable(self, variable: str) -> None:
        """Given an unparseable value, the error names the offending variable
        (REC-4: fail fast, naming the variable)."""
        with pytest.raises(ValidationError) as exc_info:
            load_search_config({variable: "abc"})

        assert variable in str(exc_info.value)

    def test_default_limit_above_max_limit_raises(self) -> None:
        """Given default_limit > max_limit, load fails fast naming the variables
        involved (REC-4)."""
        with pytest.raises(ValidationError) as exc_info:
            load_search_config({"RECALL_DEFAULT_LIMIT": "100", "RECALL_MAX_LIMIT": "50"})

        message = str(exc_info.value)
        assert "RECALL_DEFAULT_LIMIT" in message or "RECALL_MAX_LIMIT" in message

    def test_default_limit_equal_to_max_limit_accepted(self) -> None:
        """Given default_limit == max_limit, load succeeds (only '>' is rejected)."""
        config = load_search_config({"RECALL_DEFAULT_LIMIT": "20", "RECALL_MAX_LIMIT": "20"})

        assert config.default_limit == config.max_limit == 20

    @pytest.mark.parametrize("value", ["0.9", "0.01", "0.0", "-0.05", "1"])
    def test_project_boost_outside_adr_0010_bounds_raises(self, value: str) -> None:
        """Given project_boost outside ADR-0010's (0.02, 0.17), load fails and the
        error names RECALL_PROJECT_BOOST (REC-4)."""
        with pytest.raises(ValidationError) as exc_info:
            load_search_config({"RECALL_PROJECT_BOOST": value})

        assert "RECALL_PROJECT_BOOST" in str(exc_info.value)

    @pytest.mark.parametrize("value", ["0.03", "0.1", "0.16"])
    def test_project_boost_inside_bounds_accepted(self, value: str) -> None:
        """Given project_boost strictly inside (0.02, 0.17), load succeeds."""
        assert load_search_config({"RECALL_PROJECT_BOOST": value}).project_boost == float(value)
