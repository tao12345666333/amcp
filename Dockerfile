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

# Expose port for Gradio
EXPOSE 7860

# Run Gradio app
CMD ["python", "app.py"]
