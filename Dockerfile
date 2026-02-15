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

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ripgrep \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create config directory
RUN mkdir -p /root/.config/amcp

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check — hits the server /api/v1/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4096/api/v1/health')" || exit 1

EXPOSE 4096

ENTRYPOINT ["amcp"]
CMD ["serve", "--host", "0.0.0.0"]
