#!/usr/bin/env bash
set -euo pipefail

if [ -f "$(dirname "$0")/../.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$(dirname "$0")/../.env"
  set +a
fi

PUBLIC_IP="${PUBLIC_IP:-110.238.78.42}"
KEY_PATH="${SSL_KEY_FILE:-/etc/ssl/private/app.key}"
CRT_PATH="${SSL_CERT_FILE:-/etc/ssl/certs/app.crt}"
PORT="${HTTPS_PORT:-443}"

sudo mkdir -p /etc/ssl/private /etc/ssl/certs

if [ ! -f "$KEY_PATH" ] || [ ! -f "$CRT_PATH" ]; then
  echo "Generating self-signed cert for IP ${PUBLIC_IP}"
  sudo openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$KEY_PATH" \
    -out "$CRT_PATH" \
    -subj "/CN=${PUBLIC_IP}" \
    -addext "subjectAltName = IP:${PUBLIC_IP}"
  sudo chmod 600 "$KEY_PATH"
fi

# allow non-root bind to :443
PY_BIN="$(readlink -f "$(which python3)")"
if ! getcap "$PY_BIN" | grep -q cap_net_bind_service; then
  sudo setcap 'cap_net_bind_service=+ep' "$PY_BIN"
fi

cd "$(dirname "$0")/.."

echo "Starting Uvicorn on 0.0.0.0:${PORT} with TLS"
python3 -m uvicorn backend.app.main:app \
  --host 0.0.0.0 --port "${PORT}" 
