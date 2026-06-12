#!/usr/bin/env bash
# Enlaza la voz Mateo (snap) donde speech-dispatcher la puede cargar.
# Útil si prefieres spd-say en lugar del modo directo snap del host nativo.
set -euo pipefail

MATEO_SRC="/var/snap/rhvoice/common/var/lib/RHVoice/install/voice-mateo-4-11"
MATEO_DST="/usr/share/RHVoice/voices/mateo"

if [[ ! -d "$MATEO_SRC" ]]; then
  echo "Mateo no está instalado. Ejecuta: sudo rhvoice.vm -i mateo"
  exit 1
fi

echo "Enlazando $MATEO_SRC -> $MATEO_DST"
sudo ln -sfn "$MATEO_SRC" "$MATEO_DST"
systemctl --user restart speech-dispatcher 2>/dev/null || true
sleep 1

echo ""
echo "Voces RHVoice visibles para speech-dispatcher:"
spd-say -L -o rhvoice 2>/dev/null | grep -i mateo || spd-say -L -o rhvoice 2>/dev/null || true
echo ""
echo "Probar:"
echo "  spd-say -o rhvoice -y mateo -l es 'Hola, prueba en español'"
