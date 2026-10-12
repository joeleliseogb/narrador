#!/usr/bin/env bash
# ==============================================================================
# Instalador de Narrador de Libros para GNU/Linux
# Instala la aplicación en el menú de aplicaciones del sistema del usuario,
# crea el comando ejecutable 'narrador' en PATH y registra los tipos MIME.
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_BASE="$HOME/.local/share/icons/hicolor"

echo "========================================================"
echo "  Instalando Narrador de Libros en GNU/Linux"
echo "========================================================"
echo "Directorio de la aplicación: $DIR"

# 1. Comprobar Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Error: Python 3 no está instalado en el sistema."
    exit 1
fi
echo "✓ Python 3 detectado: $(python3 --version)"

# 2. Instalar dependencias de Python (si faltan)
echo "📦 Verificando dependencias de Python..."
if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    PIP_CMD="pip3"
    command -v pip3 &>/dev/null || PIP_CMD="pip"
    $PIP_CMD install --user -r "$DIR/libro/requirements.txt" --quiet || {
        echo "⚠️ Aviso: No se pudieron instalar algunos paquetes vía pip con --user."
        echo "   Si usas un entorno administrado por distro, asegúrate de tener las dependencias del sistema instaladas."
    }
fi

# 3. Crear directorio de binarios del usuario
mkdir -p "$BIN_DIR"

LAUNCHER="$BIN_DIR/narrador"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Lanzador de Narrador de Libros
exec python3 "$DIR/libro/narrador-gui.py" "\$@"
EOF
chmod +x "$LAUNCHER"
echo "✓ Ejecutable creado en: $LAUNCHER"

# 4. Instalar iconos en el tema del sistema
echo "🎨 Instalando iconos de la aplicación..."
mkdir -p "$ICON_BASE/scalable/apps"
mkdir -p "$ICON_BASE/512x512/apps"
mkdir -p "$ICON_BASE/256x256/apps"
mkdir -p "$ICON_BASE/128x128/apps"
mkdir -p "$ICON_BASE/64x64/apps"
mkdir -p "$ICON_BASE/48x48/apps"
mkdir -p "$ICON_BASE/32x32/apps"
mkdir -p "$ICON_BASE/16x16/apps"
mkdir -p "$HOME/.local/share/pixmaps"

[ -f "$DIR/icons/narrador.svg" ] && cp "$DIR/icons/narrador.svg" "$ICON_BASE/scalable/apps/narrador.svg"
[ -f "$DIR/icons/icon512.png" ] && cp "$DIR/icons/icon512.png" "$ICON_BASE/512x512/apps/narrador.png"
[ -f "$DIR/icons/icon256.png" ] && cp "$DIR/icons/icon256.png" "$ICON_BASE/256x256/apps/narrador.png"
[ -f "$DIR/icons/icon128.png" ] && cp "$DIR/icons/icon128.png" "$ICON_BASE/128x128/apps/narrador.png"
[ -f "$DIR/icons/icon64.png" ] && cp "$DIR/icons/icon64.png" "$ICON_BASE/64x64/apps/narrador.png"
[ -f "$DIR/icons/icon48.png" ] && cp "$DIR/icons/icon48.png" "$ICON_BASE/48x48/apps/narrador.png"
[ -f "$DIR/icons/icon32.png" ] && cp "$DIR/icons/icon32.png" "$ICON_BASE/32x32/apps/narrador.png"
[ -f "$DIR/icons/icon16.png" ] && cp "$DIR/icons/icon16.png" "$ICON_BASE/16x16/apps/narrador.png"

# Iconos de respaldo en pixmaps y tema base
[ -f "$DIR/icons/narrador.svg" ] && cp "$DIR/icons/narrador.svg" "$HOME/.local/share/pixmaps/narrador.svg" 2>/dev/null || true
[ -f "$DIR/icons/icon256.png" ] && cp "$DIR/icons/icon256.png" "$HOME/.local/share/pixmaps/narrador.png" 2>/dev/null || true
[ -f "$DIR/icons/icon128.png" ] && cp "$DIR/icons/icon128.png" "$HOME/.local/share/icons/narrador.png" 2>/dev/null || true
[ -f "$DIR/icons/narrador.svg" ] && cp "$DIR/icons/narrador.svg" "$HOME/.local/share/icons/narrador.svg" 2>/dev/null || true

# Eliminar accesos directos obsoletos o duplicados si existían
rm -f "$APP_DIR/narrador-libros.desktop"

# 5. Crear archivo .desktop en el menú de aplicaciones
mkdir -p "$APP_DIR"
DESKTOP_FILE="$APP_DIR/narrador.desktop"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Narrador de Libros
GenericName=Lector de Libros y Audiolibros TTS
Comment=Lee libros, PDFs, EPUBs y documentos en voz alta con voces neuronales y expórtalos a MP3
Exec="$LAUNCHER" %U
Icon=narrador
Terminal=false
Categories=AudioVideo;Audio;Office;Viewer;Education;
MimeType=application/pdf;application/epub+zip;text/plain;application/vnd.openxmlformats-officedocument.wordprocessingml.document;application/vnd.oasis.opendocument.text;
Keywords=audiolibro;narrador;tts;lector;voz;pdf;epub;audio;libro;
StartupNotify=true
StartupWMClass=narrador
EOF
chmod +x "$DESKTOP_FILE"
echo "✓ Acceso directo creado en: $DESKTOP_FILE"

# 6. Actualizar bases de datos de escritorio e iconos
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
fi

# Actualizar caché de servicios de KDE Plasma si está disponible
if command -v kbuildsycoca6 &>/dev/null; then
    kbuildsycoca6 --noincremental 2>/dev/null || kbuildsycoca6 2>/dev/null || true
elif command -v kbuildsycoca5 &>/dev/null; then
    kbuildsycoca5 --noincremental 2>/dev/null || kbuildsycoca5 2>/dev/null || true
fi

echo ""
echo "========================================================"
echo "🎉 ¡Instalación completada con éxito!"
echo "========================================================"
echo "• Ya aparece en la lista de programas de tu sistema (Menú de Aplicaciones)."
echo "• Puedes abrirlo buscando 'Narrador de Libros' en tus aplicaciones."
echo "• Puedes ejecutarlo desde cualquier terminal con el comando: narrador"
echo "• Puedes asociar archivos PDF o EPUB para abrirlos directamente con Narrador."
echo "========================================================"
