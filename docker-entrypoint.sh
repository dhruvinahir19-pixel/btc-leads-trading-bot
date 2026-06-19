#!/bin/bash
# =============================================================================
# docker-entrypoint.sh — Hugging Face Spaces Docker entrypoint.
#
# Starts Tor + Privoxy to route outbound Binance API traffic through the Tor
# network, bypassing Binance's geo-restriction from US-based HF Spaces servers.
# Then drops privileges to appuser and exec's the CMD (uvicorn).
# =============================================================================
set -e

# ── Write a minimal Privoxy config that forwards HTTP → Tor SOCKS5 ──
# forward-socks5t = SOCKS5 with Torify (DNS resolution goes through Tor too)
cat > /tmp/privoxy-config << 'PRIVOXY_EOF'
listen-address  127.0.0.1:8118
forward-socks5t / 127.0.0.1:9050 .
PRIVOXY_EOF

# ── Start Tor daemon ──
# Tor drops privileges to the debian-tor user automatically (configured in
# /etc/tor/torrc by the Debian package). It listens on 127.0.0.1:9050 for
# SOCKS5 connections.
echo "[entrypoint] Starting Tor (SOCKS5 on 127.0.0.1:9050)..."
tor &

# ── Start Privoxy ──
# Privoxy bridges HTTP proxy requests into Tor's SOCKS5.
# Listens on 127.0.0.1:8118.
echo "[entrypoint] Starting Privoxy (HTTP proxy on 127.0.0.1:8118)..."
privoxy /tmp/privoxy-config &

# ── Wait for Tor SOCKS5 port ──
echo "[entrypoint] Waiting for Tor to become ready..."
TOR_OK=0
for i in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/9050) 2>/dev/null; then
        echo "[entrypoint] Tor SOCKS5 ready on port 9050"
        TOR_OK=1
        break
    fi
    sleep 1
done
if [ "$TOR_OK" -ne 1 ]; then
    echo "[entrypoint] WARNING: Tor did not start within 30s. Binance requests may fail."
fi

# ── Wait for Privoxy port ──
echo "[entrypoint] Waiting for Privoxy to become ready..."
PRIVOXY_OK=0
for i in $(seq 1 15); do
    if (echo > /dev/tcp/127.0.0.1/8118) 2>/dev/null; then
        echo "[entrypoint] Privoxy HTTP proxy ready on port 8118"
        PRIVOXY_OK=1
        break
    fi
    sleep 1
done
if [ "$PRIVOXY_OK" -ne 1 ]; then
    echo "[entrypoint] WARNING: Privoxy did not start within 15s."
fi

# ── Drop privileges to appuser and launch the application ──
# sudo -E preserves environment variables, -u appuser runs the command
# as non-root. Using exec means sudo becomes PID 1 and forwards Docker
# signals (SIGTERM, etc.) properly to the uvicorn process.
# "$@" passes through the CMD array arguments cleanly.
echo "[entrypoint] Dropping privileges to appuser and launching application..."
exec sudo -E -u appuser -- "$@"
