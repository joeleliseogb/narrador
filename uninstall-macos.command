#!/usr/bin/env bash
# ==============================================================================
# Desinstalador de Narrador de Libros para macOS
# ==============================================================================

set -e

APP_TARGET="$HOME/Applications/Narrador.app"
BIN_DIR="$HOME/.local/bin"

echo "========================================================"
echo "  Desinstalando Narrador de Libros de macOS"
echo "========================================================"

if [ -d "$APP_TARGET" ]; then
    rm -rf "$APP_TARGET"
    echo "✓ Eliminado: $APP_TARGET"
fi

rm -f "$BIN_DIR/narrador"
echo "✓ Eliminado comando de terminal: $BIN_DIR/narrador"

if [ -f "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister" ]; then
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$APP_TARGET" 2>/dev/null || true
fi

echo "========================================================"
echo "✓ Narrador de Libros ha sido desinstalado de macOS."
echo "========================================================"
echo ""
