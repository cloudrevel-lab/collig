# Sandbox image for the Collig web terminal.
#
# It contains the CLI and its Python dependencies, but no user data and no
# provider credentials.  Each browser session gets a fresh HOME and workspace
# bind-mounted at runtime by core/terminal.py.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first so code edits do not invalidate the expensive sync.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY core ./core
COPY agents ./agents
COPY skills ./skills
COPY terminal ./terminal
COPY assets ./assets
COPY main.py ./

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 --shell /bin/bash collig \
    && chown -R collig:collig /app \
    && chmod -R a+rX /app

USER collig
WORKDIR /workspace

CMD ["python", "/app/core/cli.py"]
