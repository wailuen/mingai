# INFRA-040: Dockerfile for mingai backend
FROM python:3.11-slim AS base

# Security: run as non-root user
RUN groupadd -r mingai && useradd -r -g mingai mingai

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY . .

# Switch to non-root user
USER mingai

# Expose port
EXPOSE 8022

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8022/health'); assert r.status_code == 200"

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8022"]
