# Recall

Focused MCP memory server for coding agents.

## Local setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux/macOS
# or: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# Install dependencies
uv sync --extra dev
```

## Running checks

```bash
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run mypy                      # Type-check (strict)
uv run pytest -m "not integration"  # Unit tests
uv run pytest -m integration     # Integration tests (needs Docker)
uv run pytest                    # All tests
```

## Database

```bash
# Run schema setup against a Postgres instance
DATABASE_URL=postgresql://user:pass@localhost:5432/recall uv run recall db migrate

# Start server (auto-migrates by default)
DATABASE_URL=postgresql://user:pass@localhost:5432/recall uv run recall serve
```

Set `RECALL_DB_MIGRATE_ON_STARTUP=false` to skip auto-migration on serve.

## Docker Compose

```bash
docker compose up    # Starts Postgres+pgvector and Recall together
```
