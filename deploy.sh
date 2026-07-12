#!/bin/bash
set -e

PI_USER="${TOBIGT_PI_USER:-tobi}"
PI_HOST="${TOBIGT_PI_HOST:-192.168.60.1}"
PI_DIR="${TOBIGT_PI_DIR:-/home/tobi/tobigt-puente-pipedal}"

echo "=== Deploy TobiGT bridge to PiPedal ==="
echo "Target: $PI_USER@$PI_HOST:$PI_DIR"
echo ""

# Sync files (exclude .git, __pycache__, etc)
rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.gitignore' \
    "$(dirname "$0")/" \
    "$PI_USER@$PI_HOST:$PI_DIR/"

echo ""
echo "Sync done. Running setup on Pi..."
ssh "$PI_USER@$PI_HOST" "cd $PI_DIR && ./setup.sh"

echo ""
echo "=== Done ==="
