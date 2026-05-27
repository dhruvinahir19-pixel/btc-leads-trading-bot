#!/usr/bin/env bash
# =============================================================================
# render-build.sh - Build script for Render Web Service
# Installs Python dependencies and builds the React frontend
# =============================================================================
set -e  # Exit on any error

echo "========================================"
echo "  Starting Render build..."
echo "========================================"

# ─── Step 1: Install Python dependencies ───
echo "[1/3] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ─── Step 2: Build Frontend (React + Vite) ───
echo "[2/3] Building frontend..."
cd frontend
npm install
npm run build
cd ..

# ─── Step 3: Verify build output ───
echo "[3/3] Verifying build..."
if [ -d "backend/static" ] && [ -f "backend/static/index.html" ]; then
    echo "✅ Build successful! Frontend static files ready at backend/static/"
else
    echo "⚠️  Frontend build output not found at backend/static/"
    echo "   Check that vite.config.ts outputs to ../backend/static/"
fi

echo "========================================"
echo "  Build complete."
echo "========================================"
