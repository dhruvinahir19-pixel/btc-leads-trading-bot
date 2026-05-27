# =============================================================================
# Stage 1: Build Frontend (React + Vite)
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files first (for layer caching)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=optional

# Copy frontend source
COPY frontend/ .

# Build to backend/static (matches vite.config.ts outDir)
RUN npm run build

# =============================================================================
# Stage 2: Python Backend
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for curl (healthcheck) and SQLite optimizations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/backend/static/ ./backend/static/

# Create data directory for SQLite persistence (Render persistent disk or local)
RUN mkdir -p /data /app/data && chmod 755 /data /app/data

# Environment defaults (Render overrides PORT and DB_PATH via env vars)
ENV HOST=0.0.0.0
ENV LOG_LEVEL=INFO
ENV DB_PATH=/app/data/trading_bot.db

# Healthcheck: uses dynamic $PORT (Render sets PORT=10000, local defaults to 8000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

EXPOSE 8000

# Run with uvicorn using $PORT env var (Render-compatible)
# Render sets PORT=10000 automatically; locally defaults to 8000
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level ${LOG_LEVEL:-info}
