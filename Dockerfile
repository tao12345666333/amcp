# AMCP Server — Dockerfile
#
# Build:
#   docker build -t amcp .
#
# Run (interactive CLI inside the container):
#   docker run -it amcp
#
# Run server on loopback (safe default, no auth required):
#   docker run -it amcp serve
#
# Run server exposed to the host network with authentication:
#   docker run -p 8080:8080 -v ./config.toml:/root/.config/amcp/config.toml \
#       amcp serve --host 0.0.0.0
#
# With scheduler & reactor:
#   docker run -p 8080:8080 -v ./config.toml:/root/.config/amcp/config.toml \
#       amcp serve --host 0.0.0.0 --scheduler --reactor
#
# NOTE: A non-loopback --host (e.g. 0.0.0.0) requires [server.auth] to be
#       configured. Bind to loopback for unauthenticated use.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    git \
    curl \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Copy only files needed to install AMCP. Avoid sending local deployment
# files (for example e2b/env) into the runtime image and keep dependency
# installation cacheable across unrelated repository changes.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Install Python dependencies
RUN uv sync --frozen --no-dev --no-editable

# Create runtime directories
RUN mkdir -p /root/.config/amcp /workspace

WORKDIR /workspace

# Health check — hits the server /api/v1/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--", "amcp"]
CMD ["serve"]
