#!/usr/bin/env bash
# Instala el host nativo para Brave, Chrome y Microsoft Edge en macOS.

set -euo pipefail

# Asegura que el directorio de trabajo es el del script al hacer doble clic
cd "$(dirname "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(pwd)"
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

if [[ -z "$CHROMIUM_ID" ]]; then
  echo "=== Instalador del motor de voz nativo (macOS) ==="
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

echo ""
echo "Instalando host nativo en macOS…"

if [[ -n "$CHROMIUM_ID" ]]; then
  echo "Navegadores Chromium (Brave / Chrome):"
  write_host_manifest "$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts" "$CHROMIUM_ID"
  write_host_manifest "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts" "$CHROMIUM_ID"
fi

if [[ -n "$EDGE_ID" ]]; then
  echo "Microsoft Edge:"
  write_host_manifest "$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts" "$EDGE_ID"
fi

echo ""
echo "Listo. Recarga la extensión en cada navegador y prueba en YouTube."
echo ""
