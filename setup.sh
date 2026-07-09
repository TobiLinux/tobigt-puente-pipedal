#!/bin/bash
set -e

cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
VENV_DIR="$HOME/.animalmidi-pipedal"
SERVICE_DST="/etc/systemd/system/animalmidi.service"

echo "=== TobiGT PiPedal bridge setup ==="
echo "Source dir: $SCRIPT_DIR"

echo "[1/5] Installing system packages..."
sudo apt install -y python3-rtmidi python3-websockets python3-venv

echo "[2/5] Setting up virtual environment at $VENV_DIR..."
if [ -d "$VENV_DIR" ]; then
    echo "  venv already exists, skipping creation"
else
    python3 -m venv --system-site-packages "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

echo "[3/5] Creating env file at /etc/animalmidi/env..."
sudo mkdir -p /etc/animalmidi
if [ -f /etc/animalmidi/env ]; then
    echo "  /etc/animalmidi/env already exists — not overwriting"
else
    cat <<'EOF' | sudo tee /etc/animalmidi/env > /dev/null
# TobiGT — Variables de entorno (opcionales, estos son los defaults)
# Descomentar y cambiar según el setup.
#TOBIGT_UDP_HOST=10.42.0.1
#TOBIGT_UDP_PORT=20001
#TOBIGT_ESP_HOST=10.42.0.195
#TOBIGT_ESP_PORT=4097
#TOBIGT_PIPEDAL_WS=ws://127.0.0.1:80/pipedal
#TOBIGT_PIPEDAL_MIDI=PiPedal:in
#TOBIGT_MIDI_BACKEND=mido.backends.rtmidi/ALSA
EOF
    echo "  creado"
fi

echo "[4/5] Installing systemd service..."
sed -e "s|__USER__|$USER|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/animalmidi.service" | sudo tee "$SERVICE_DST" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable animalmidi
sudo systemctl restart animalmidi

echo "[5/5] Checking service status..."
sudo systemctl status animalmidi --no-pager

echo ""
echo "Done. Manage with:  systemctl [start|stop|status|restart] animalmidi"
