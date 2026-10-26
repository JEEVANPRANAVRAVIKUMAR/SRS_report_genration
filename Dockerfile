# SRS Solar Daily Log - Production Container
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files and install
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application source
COPY . /app/

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    TIMEZONE=Asia/Kolkata \
    PORT=8000

# Create persistent storage directories
RUN mkdir -p /app/data/workbooks /app/data/reports /app/data/backups /app/data/cache/incoming /app/data/evidence

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# Start the application
CMD ["python", "-m", "app.web.app"]
