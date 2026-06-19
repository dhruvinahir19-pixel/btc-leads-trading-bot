# =============================================================================
# Stage 1: Build Frontend (React + Vite)
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Copy package files first (for layer caching)
# Uses wildcard so it works whether or not package-lock.json exists
COPY frontend/package*.json ./
RUN npm ci

# Copy frontend source
COPY frontend/ .

# Build to backend/static (matches vite.config.ts outDir)
RUN npm run build

# =============================================================================
# Stage 2: Python Backend — Hugging Face Spaces Optimized
# =============================================================================
FROM python:3.10-slim

# ── Create non-root user with UID 1000 (Hugging Face Spaces requirement) ──
# Hugging Face runs containers as UID 1000. We create this user so file
# permissions work correctly and the app doesn't run as root.
RUN groupadd -g 1000 appuser && \
    useradd -m -u 1000 -g appuser -s /bin/bash appuser

# ── Install system dependencies ──
# curl is needed for the HEALTHCHECK command.
# tor + privoxy bypass Binance geo-restriction (HTTP 451) from Hugging Face US servers.
# libsqlite3-0 is already included in the slim image.
# sudo is needed by docker-entrypoint.sh to drop from root to appuser
# while preserving proper Docker signal forwarding (SIGTERM → uvicorn PID 1).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tor \
    privoxy \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# ── Switching to appuser for pip install to avoid pip root warnings ──
# We still need to install packages globally. We'll use the system pip
# then switch to appuser for runtime.
WORKDIR /app

# Copy dependency file and install (as root so pip can install globally)
COPY requirements.txt .
# python:3.10-slim (Debian 11/Bullseye) ships pip < 23.0, so
# --break-system-packages is not needed (and would be unrecognized).
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/backend/static/ ./backend/static/

# ── Create data directory for SQLite (NOTE: ephemeral in HF Spaces!) ──
# IMPORTANT: Hugging Face Spaces has EPHEMERAL storage. The SQLite database
# file stored here WILL BE LOST on every Space restart/build.
# For persistent trade history, configure an external database or use
# Hugging Face Spaces persistent storage (paid feature).
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# ── Environment defaults ──
# HF_APP is set to 1 so the app can detect it's running on HF Spaces
# (used together with SPACE_ID env var for IS_HF detection in config.py)
ENV HOST=0.0.0.0
ENV LOG_LEVEL=INFO
ENV DB_PATH=/app/data/trading_bot.db
ENV HF_APP=1
ENV TZ=Asia/Kolkata

# ── PostgreSQL SSL Configuration ──
# psycopg/libpq searches ~/.postgresql/ for client certificates by default.
# Since we run as appuser at runtime (and root's ~/.postgresql/ is inaccessible),
# set PGSSLMODE=require explicitly so libpq uses the system CA store
# (/etc/ssl/certs/) instead of looking in root's home directory.
# This avoids SSL certificate path permission errors on Neon.tech connections.
ENV PGSSLMODE=require

# ── Proxy environment (Tor → Privoxy → app) ──
# Privoxy listens on 8118 and forwards to Tor's SOCKS5 on 9050.
# BinanceClient uses this to bypass geo-restriction from HF Spaces.
# Can be overridden per-env (e.g. dev without Tor).
ENV BINANCE_PROXY=http://127.0.0.1:8118

# ── Entrypoint: starts tor + privoxy, then drops to appuser ──
# ENTRYPOINT MUST run as root so it can start the Tor daemon.
# The entrypoint script handles the drop to appuser via sudo -u.
# We intentionally do NOT set USER appuser — Docker uses the last USER
# for both ENTRYPOINT and CMD at runtime, which would prevent tor from
# starting. The HEALTHCHECK runs as root (fine — curl works as root).
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# ── HEALTHCHECK ──
# Hugging Face Spaces uses port 7860 internally for routing external traffic
# to the container. The app MUST listen on this port.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

EXPOSE 7860

# ── Startup Command ──
# Binds to 0.0.0.0:7860 as required by Hugging Face Spaces.
# The app starts the trading bot scheduler and WebSocket manager
# inside the FastAPI lifespan, so both the web server and background
# trading threads run in a single process.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860", "--log-level", "info"]
