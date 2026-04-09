# syntax=docker/dockerfile:1.7
# Multi-stage build for the Recall MCP memory server.

# ---- builder ----------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install uv for fast, deterministic installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project metadata first to maximise layer caching.
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src

# Install into a relocatable venv at /app/.venv
RUN uv sync --frozen --no-dev || uv sync --no-dev

# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system recall && useradd --system --gid recall --home /app recall

WORKDIR /app

COPY --from=builder /app /app
RUN chown -R recall:recall /app

USER recall

EXPOSE 8080

# Healthcheck hits /healthz (see S5.4).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)"

CMD ["recall", "serve"]
