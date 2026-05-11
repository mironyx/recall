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

`docker compose up` starts Postgres 17 + pgvector and Recall together:

```bash
docker compose up
```

- **Postgres** is available on port 5432 (user `recall`, password `recall`, database `recall`).
- **Recall** is available on port 8080. On startup it auto-migrates the database schema.
- Health checks: Postgres must be healthy before Recall starts. Recall's `/healthz` endpoint is used as the container health check.
- Data persists in a `pgdata` named volume.

Verify everything is running:

```bash
curl http://localhost:8080/healthz
# → {"status":"ok"}
```

### MCP client configuration

After the MCP endpoint lands (Phase 1), point your MCP client at Recall with this snippet:

```json
{
  "mcpServers": {
    "recall": {
      "url": "http://localhost:8080/mcp",
      "headers": {
        "Authorization": "Bearer <your-token>"
      }
    }
  }
}
```

For Claude Code, add the snippet to `~/.claude/claude_desktop_config.json` (or the equivalent for your IDE/agent). For Cursor, use `.cursor/mcp.json`.
