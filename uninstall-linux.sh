#!/usr/bin/env bash
# ==============================================================================
# Desinstalador de Narrador de Libros para GNU/Linux
# ==============================================================================

set -e

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_BASE="$HOME/.local/share/icons/hicolor"

echo "========================================================"
echo "  Desinstalando Narrador de Libros de GNU/Linux"
echo "========================================================"

rm -f "$BIN_DIR/narrador"
echo "✓ Eliminado ejecutable: $BIN_DIR/narrador"

rm -f "$APP_DIR/narrador.desktop"
echo "✓ Eliminado acceso de menú: $APP_DIR/narrador.desktop"

rm -f "$ICON_BASE/128x128/apps/narrador.png"
rm -f "$ICON_BASE/48x48/apps/narrador.png"
rm -f "$ICON_BASE/16x16/apps/narrador.png"
rm -f "$HOME/.local/share/icons/narrador.png"
echo "✓ Eliminados iconos del sistema."

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "========================================================"
echo "✓ Narrador de Libros ha sido desinstalado de tu sistema."
echo "========================================================"
