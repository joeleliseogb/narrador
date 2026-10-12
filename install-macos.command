#!/usr/bin/env bash
# ==============================================================================
# Instalador de Narrador de Libros para macOS
# Crea la aplicación nativa 'Narrador.app' en ~/Applications,
# la registra en Launchpad, Spotlight y en el Dock.
# (Se puede ejecutar por terminal o haciendo doble clic en este archivo).
# ==============================================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_TARGET="$HOME/Applications/Narrador.app"
BIN_DIR="$HOME/.local/bin"

echo "========================================================"
echo "  Instalando Narrador de Libros en macOS"
echo "========================================================"
echo "Directorio de origen: $DIR"

# 1. Comprobar Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Error: Python 3 no está instalado en este Mac."
    echo "Instálalo ejecutando: xcode-select --install  o  brew install python"
    read -p "Presiona Enter para salir..."
    exit 1
fi
echo "✓ Python 3 detectado: $(python3 --version)"

# 2. Instalar dependencias de Python
echo "📦 Instalando/verificando dependencias de Python..."
python3 -m pip install -r "$DIR/libro/requirements.txt" --quiet || {
    echo "⚠️ Aviso: No se pudieron instalar algunos paquetes vía pip."
}

# 3. Crear estructura de la aplicación macOS (.app)
echo "🍏 Creando paquete de aplicación: $APP_TARGET..."
mkdir -p "$HOME/Applications"
rm -rf "$APP_TARGET"

mkdir -p "$APP_TARGET/Contents/MacOS"
mkdir -p "$APP_TARGET/Contents/Resources"

# 4. Crear ejecutable de la aplicación
LAUNCHER="$APP_TARGET/Contents/MacOS/Narrador"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Lanzador macOS para Narrador de Libros
DIR="$DIR"
export PATH="/usr/local/bin:/opt/homebrew/bin:\$PATH"
exec /usr/bin/env python3 "\$DIR/libro/narrador-gui.py" "\$@"
EOF
chmod +x "$LAUNCHER"

# 5. Generar Icono nativo (.icns) si están disponibles sips e iconutil
ICNS_FILE="$APP_TARGET/Contents/Resources/narrador.icns"
PNG_SOURCE="$DIR/icons/icon128.png"

if command -v iconutil &>/dev/null && command -v sips &>/dev/null && [ -f "$PNG_SOURCE" ]; then
    ICONSET_DIR="/tmp/narrador_icon.iconset"
    rm -rf "$ICONSET_DIR"
    mkdir -p "$ICONSET_DIR"
    sips -z 16 16     "$PNG_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null 2>&1 || true
    sips -z 32 32     "$PNG_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null 2>&1 || true
    sips -z 32 32     "$PNG_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null 2>&1 || true
    sips -z 64 64     "$PNG_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null 2>&1 || true
    sips -z 128 128   "$PNG_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null 2>&1 || true
    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_FILE" >/dev/null 2>&1 || true
    rm -rf "$ICONSET_DIR"
fi

if [ ! -f "$ICNS_FILE" ] && [ -f "$PNG_SOURCE" ]; then
    cp "$PNG_SOURCE" "$APP_TARGET/Contents/Resources/icon.png"
fi

# 6. Crear Info.plist con metadatos completos
cat > "$APP_TARGET/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Narrador</string>
    <key>CFBundleIconFile</key>
    <string>narrador.icns</string>
    <key>CFBundleIdentifier</key>
    <string>com.narrador.app</string>
    <key>CFBundleName</key>
    <string>Narrador de Libros</string>
    <key>CFBundleDisplayName</key>
    <string>Narrador de Libros</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
</dict>
</plist>
EOF

# 7. Crear enlace en terminal (~/.local/bin/narrador)
mkdir -p "$BIN_DIR"
ln -sf "$LAUNCHER" "$BIN_DIR/narrador"

# 8. Notificar a Launch Services para indexar inmediatamente
if [ -f "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister" ]; then
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_TARGET" 2>/dev/null || true
fi
touch "$APP_TARGET"

echo ""
echo "========================================================"
echo "🎉 ¡Instalación en macOS completada con éxito!"
echo "========================================================"
echo "• Se ha creado la aplicación en: ~/Applications/Narrador.app"
echo "• Ya está disponible en Spotlight (Cmd + Espacio -> Narrador) y Launchpad."
echo "• Puedes arrastrarla al Dock si deseas tenerla a mano."
echo "• Puedes ejecutarla desde Terminal con: narrador"
echo "========================================================"
echo ""
