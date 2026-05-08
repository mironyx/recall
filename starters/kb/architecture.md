# Architecture

## Boundary rule

`src/recall/db/` must have zero imports from `src/recall/server.py` or any MCP transport code. Storage layer is a leaf — it depends on nothing in the application.

## API composition pattern

Single-container MCP server. `src/recall/server.py` is the composition root: it wires Auth → Tool Router → Memory Service → Embedder → Postgres. No DI framework — manual constructor injection at startup.
