#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== TobiGT PiPedal bridge update ==="

# Intentar actualizar desde git si hay remote configurado
if git rev-parse --is-inside-work-tree &>/dev/null; then
    REMOTE=$(git remote 2>/dev/null | head -1)
    if [ -n "$REMOTE" ]; then
        BRANCH=$(git rev-parse --abbrev-ref HEAD)
        echo "Repositorio git detectado — remote: $REMOTE, rama: $BRANCH"
        git pull "$REMOTE" "$BRANCH"
        echo ""
    else
        echo "Repositorio git sin remote — saltando git pull"
        echo "  Para configurar:  git remote add origin <url>"
        echo ""
    fi
else
    echo "No es un repositorio git — copia los archivos manualmente o pon el proyecto bajo git"
    echo ""
fi

echo "Re-ejecutando setup..."
exec ./setup.sh
