# Conventions

| Concept | Pattern |
|---|---|
| test-suffix | `test_*.py` |
| test-path | `tests/test_<module>.py` |
| eval-test-path | `tests/evaluation/test_<slug>_eval.py` |
| conftest | `tests/conftest.py` |
| source-dir | `src/recall/` |
| integration-marker | `@pytest.mark.integration` |
| migration-generate-cmd | `uv run recall db migrate` |
| serve-cmd | `uv run recall serve` |
| install-cmd | `uv sync --extra dev` |
| lint-cmd | `uv run ruff check` |
| format-cmd | `uv run ruff format` |
| typecheck-cmd | `uv run mypy --strict` |
| test-cmd | `uv run pytest` |
| integration-test-cmd | `uv run pytest -m integration` |
| build-script | `./scripts/run-build.sh` |
| lint-script | `./scripts/run-lint.sh` |
| typecheck-script | `./scripts/run-typecheck.sh` |
| test-script | `./scripts/run-tests.sh` |
| format-check-script | `./scripts/run-format-check.sh` |
| markdown-lint-script | `./scripts/run-markdown-lint.sh` |
| e2e-script | `./scripts/run-e2e.sh` |
| gh-project-status-script | `./scripts/gh-project-status.sh` |
