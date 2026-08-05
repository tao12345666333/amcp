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
# Run server exposed to the host network with authentication (via env vars):
#   docker run -p 8080:8080 \
#       -e AMCP_HOST=0.0.0.0 -e AMCP_API_KEY=your-secret \
#       amcp serve
#
# Run server exposed to the host network with authentication (via config file):
#   docker run -p 8080:8080 -v ./config.toml:/root/.config/amcp/config.toml \
#       amcp serve --host 0.0.0.0
#
# With scheduler & reactor:
#   docker run -p 8080:8080 \
#       -e AMCP_HOST=0.0.0.0 -e AMCP_API_KEY=your-secret \
#       amcp serve --scheduler --reactor
#
# NOTE: A non-loopback --host (e.g. 0.0.0.0) requires authentication.
#       Use --api-key, AMCP_API_KEY env var, or [server.auth] in config.toml.
#       Custom ports via AMCP_PORT are picked up by the HEALTHCHECK automatically.

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
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:%s/api/v1/health' % os.environ.get('AMCP_PORT', '8080'))" || exit 1

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--", "amcp"]
CMD ["serve"]
