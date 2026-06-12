#!/usr/bin/env bash
# Instala edge-tts (voces neuronales online de Microsoft Edge).
set -euo pipefail

echo "Instalando edge-tts (voces neuronales online)..."
pip3 install --user --upgrade edge-tts

if command -v edge-tts >/dev/null; then
  echo ""
  echo "Listo. Voces en español disponibles:"
  edge-tts --list-voices | grep -i '^es-' | head -10
  echo ""
  echo "Prueba:"
  echo "  edge-tts --voice es-ES-ElviraNeural --text 'Hola, prueba neuronal'"
else
  echo "Asegúrate de que ~/.local/bin está en tu PATH."
fi
