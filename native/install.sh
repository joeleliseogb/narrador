#!/usr/bin/env bash
# Instala el host nativo para Brave, Chrome, Chromium y Microsoft Edge (Linux).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_PY="$SCRIPT_DIR/narrador-host.py"
LAUNCHER="$HOME/.local/bin/narrador-youtube-tts"
HOST_ID="com.narrador.youtube"

chmod +x "$HOST_PY"

mkdir -p "$HOME/.local/bin"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
export PATH="\$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:\$PATH"
exec python3 "$HOST_PY"
EOF
chmod +x "$LAUNCHER"

write_host_manifest() {
  local base_dir="$1"
  local ext_id="$2"
  [[ -n "$ext_id" ]] || return 0
  mkdir -p "$base_dir"
  cat > "$base_dir/$HOST_ID.json" <<EOF
{
  "name": "$HOST_ID",
  "description": "Narrador YouTube TTS host",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$ext_id/"
  ]
}
EOF
  echo "  ✓ $base_dir/$HOST_ID.json"
}

CHROMIUM_ID="${1:-}"
EDGE_ID="${2:-}"

# Detectar si hay entorno gráfico y zenity disponible
USE_GUI=false
if [[ -z "$CHROMIUM_ID" && ( -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ) ]]; then
  if command -v zenity &>/dev/null; then
    USE_GUI=true
  fi
fi

if [[ "$USE_GUI" == "true" ]]; then
  CHROMIUM_ID=$(zenity --entry --title="Instalador Narrador YouTube" --text="Ingresa el ID de la extensión para Brave/Chrome (ej: clcghhgepahdgjlfkfkdodllfecojjee):" --entry-text="")
  
  if [[ -z "$CHROMIUM_ID" ]]; then
    if zenity --question --title="Instalador Narrador YouTube" --text="¿Deseas configurar la extensión únicamente para Microsoft Edge?" --ok-label="Sí" --cancel-label="No"; then
      EDGE_ID=$(zenity --entry --title="Instalador Narrador YouTube" --text="Ingresa el ID de la extensión para Microsoft Edge:" --entry-text="")
      CHROMIUM_ID=""
    else
      zenity --error --title="Instalador Narrador YouTube" --text="Instalación cancelada: se requiere un ID de extensión."
      exit 1
    fi
  else
    if [[ ${#CHROMIUM_ID} -lt 20 ]]; then
      zenity --error --title="Instalador Narrador YouTube" --text="Error: El ID ingresado es demasiado corto o inválido."
      exit 1
    fi
    if zenity --question --title="Instalador Narrador YouTube" --text="¿Deseas usar la extensión también en Microsoft Edge con el mismo ID?" --ok-label="Sí" --cancel-label="No"; then
      EDGE_ID="$CHROMIUM_ID"
    else
      if zenity --question --title="Instalador Narrador YouTube" --text="¿Quieres ingresar un ID diferente para Microsoft Edge?" --ok-label="Sí" --cancel-label="Omitir Edge"; then
        EDGE_ID=$(zenity --entry --title="Instalador Narrador YouTube" --text="Ingresa el ID de la extensión para Microsoft Edge:" --entry-text="")
      else
        EDGE_ID=""
      fi
    fi
  fi
else
  # Modo Texto normal (consola)
  if [[ -z "$CHROMIUM_ID" ]]; then
    echo "=== Instalador del motor de voz nativo ==="
    echo ""
    echo "Necesitas el ID de la extensión en cada navegador donde la uses."
    echo "  Brave:  brave://extensions/"
    echo "  Chrome: chrome://extensions/"
    echo "  Edge:   edge://extensions/"
    echo "  (Modo desarrollador activado → copiar ID)"
    echo ""
    read -rp "ID Brave / Chrome / Chromium: " CHROMIUM_ID

    if [[ -z "$CHROMIUM_ID" ]]; then
      read -rp "¿Solo Microsoft Edge? Pega el ID de Edge: " CHROMIUM_ID
    fi

    if [[ -z "$CHROMIUM_ID" ]]; then
      echo "Error: hace falta al menos un ID."
      exit 1
    fi

    if [[ ${#CHROMIUM_ID} -lt 20 ]]; then
      echo "Error: el ID parece incompleto (suele tener 32 caracteres)."
      exit 1
    fi

    echo ""
    read -rp "ID de Edge (Enter = mismo ID; escribe 'no' para omitir Edge): " EDGE_ANSWER
    if [[ -z "$EDGE_ANSWER" ]]; then
      EDGE_ID="$CHROMIUM_ID"
    elif [[ "${EDGE_ANSWER,,}" != "no" && "${EDGE_ANSWER,,}" != "n" ]]; then
      EDGE_ID="$EDGE_ANSWER"
    fi
  else
    if [[ -z "$EDGE_ID" ]]; then
      EDGE_ID="$CHROMIUM_ID"
    elif [[ "${EDGE_ID,,}" == "no" || "${EDGE_ID,,}" == "n" ]]; then
      EDGE_ID=""
    fi
  fi
fi

echo ""
echo "Instalando host nativo…"

if [[ -n "$CHROMIUM_ID" ]]; then
  echo "Navegadores Chromium (Brave / Chrome / Chromium):"
  for BASE in \
    "$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts" \
    "$HOME/.config/google-chrome/NativeMessagingHosts" \
    "$HOME/.config/chromium/NativeMessagingHosts" \
    "$HOME/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser/NativeMessagingHosts" \
    "$HOME/.var/app/com.google.Chrome/config/google-chrome/NativeMessagingHosts" \
    "$HOME/.var/app/org.chromium.Chromium/config/chromium/NativeMessagingHosts"
  do
    write_host_manifest "$BASE" "$CHROMIUM_ID"
  done
fi

if [[ -n "$EDGE_ID" ]]; then
  echo "Microsoft Edge:"
  for BASE in \
    "$HOME/.config/microsoft-edge/NativeMessagingHosts" \
    "$HOME/.config/microsoft-edge-beta/NativeMessagingHosts" \
    "$HOME/.var/app/com.microsoft.Edge/config/microsoft-edge/NativeMessagingHosts"
  do
    write_host_manifest "$BASE" "$EDGE_ID"
  done
fi

echo ""
echo "Listo. Recarga la extensión en cada navegador y prueba en YouTube."
echo ""
echo "Lector de libros (EPUB/TXT):"
echo "  pip install --user ebooklib beautifulsoup4"
echo "  python3 \"$(dirname "$SCRIPT_DIR")/libro/narrador-libro.py\" --help"
