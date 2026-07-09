# AMCP Server — Dockerfile
#
# Build:
#   docker build -t amcp .
#
# Run:
#   docker run -p 4096:4096 amcp
#   docker run -p 4096:4096 -v /path/to/project:/workspace amcp \
#       serve --host 0.0.0.0 --work-dir /workspace
#
# With scheduler & reactor:
#   docker run -p 4096:4096 -v ./config.toml:/root/.config/amcp/config.toml \
#       amcp serve --host 0.0.0.0 --scheduler --reactor

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
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4096/api/v1/health')" || exit 1

EXPOSE 4096

ENTRYPOINT ["/usr/bin/tini", "--", "amcp"]
CMD ["serve", "--host", "0.0.0.0"]
