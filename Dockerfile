FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ripgrep \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for MCP servers
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create config directory
RUN mkdir -p /root/.config/amcp

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default command
CMD ["amcp"]
