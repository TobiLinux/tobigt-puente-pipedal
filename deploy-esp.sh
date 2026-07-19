#!/bin/bash
set -e

PORT="${TOBIGT_ESP_PORT:-/dev/ttyUSB1}"
BAUD="${TOBIGT_ESP_BAUD:-115200}"
SRC_DIR="$(dirname "$0")/esp-firmware"

echo "=== Deploy TobiGT firmware to ESP ==="
echo "Port: $PORT  Baud: $BAUD"
echo "Source: $SRC_DIR"
echo ""

# Remove compiled .mpy so .py is used
for f in "$SRC_DIR"/*.mpy; do
    base="$(basename "$f" .mpy).py"
    if [ -f "$SRC_DIR/$base" ]; then
        echo "Removing ${base%.py}.mpy (using $base instead)"
        ampy --port "$PORT" --baud "$BAUD" rm "/${base%.py}.mpy" 2>/dev/null || true
    fi
done

# Upload all .py files
for f in "$SRC_DIR"/*.py; do
    dest="/$(basename "$f")"
    echo "Uploading $(basename "$f")..."
    ampy --port "$PORT" --baud "$BAUD" put "$f" "$dest"
done

# Upload config.json if present
if [ -f "$SRC_DIR/config.json" ]; then
    echo "Uploading config.json..."
    ampy --port "$PORT" --baud "$BAUD" put "$SRC_DIR/config.json" /config.json
fi

echo ""
echo "=== Done. Reset the ESP to apply changes. ==="
