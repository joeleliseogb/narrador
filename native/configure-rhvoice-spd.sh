#!/usr/bin/env bash
# Activa RHVoice en speech-dispatcher y apunta a las voces instaladas con snap (Mateo, etc.)
set -euo pipefail

SPD_CONF="/etc/speech-dispatcher/speechd.conf"
RHVOICE_CONF="/etc/speech-dispatcher/modules/rhvoice.conf"
SPD_MOD="/usr/lib64/speech-dispatcher-modules/sd_rhvoice"
SNAP_DATA="/var/snap/rhvoice/common/var/lib/RHVoice/data/RHVoice"

echo "============================================"
echo "  Configurar RHVoice + speech-dispatcher"
echo "============================================"
echo ""

if [[ ! -d "$SNAP_DATA/voices/mateo" ]] && [[ ! -d "$SNAP_DATA/voices" ]]; then
  echo "No hay voces RHVoice en snap. Instala Mateo primero:"
  echo "  sudo rhvoice.vm -i mateo"
  exit 1
fi

echo "Paso 1/4: Restaurar sd_rhvoice del paquete Fedora (enlace snap roto)..."
if [[ -L "$SPD_MOD" ]] && [[ ! -e "$SPD_MOD" ]]; then
  sudo rm -f "$SPD_MOD"
fi
if [[ ! -x "$SPD_MOD" ]]; then
  sudo dnf reinstall -y rhvoice-speech-dispatcher-plugin
fi

echo ""
echo "Paso 2/4: Crear $RHVOICE_CONF ..."
sudo tee "$RHVOICE_CONF" >/dev/null <<EOF
RHVoiceDataPath "$SNAP_DATA"
RHVoiceConfigPath "/usr/etc/RHVoice"
RHVoiceDefaultVoice "mateo"
Debug 0
EOF

echo ""
echo "Paso 3/4: Activar módulo rhvoice en speechd.conf ..."
if grep -q '^#AddModule "rhvoice"' "$SPD_CONF"; then
  sudo sed -i 's/^#AddModule "rhvoice"/AddModule "rhvoice"/' "$SPD_CONF"
elif ! grep -q '^AddModule "rhvoice"' "$SPD_CONF"; then
  echo 'AddModule "rhvoice"                  "sd_rhvoice"   "rhvoice.conf"' | sudo tee -a "$SPD_CONF" >/dev/null
fi

echo ""
echo "Paso 4/4: Reiniciar speech-dispatcher ..."
systemctl --user restart speech-dispatcher 2>/dev/null || true
sleep 1

echo ""
echo "Comprobación:"
spd-say -O
echo ""
spd-say -L 2>/dev/null | grep -iE 'rhvoice|mateo' || echo "(si no aparece Mateo, reinicia sesión o ejecuta: killall speech-dispatcher; speech-dispatcher -d)"
echo ""
echo "Nota: el módulo sd_rhvoice de Fedora a menudo NO carga voces snap (solo inglés)."
echo "El host nativo Narrador usa rhvoice.test directo para Mateo (v2.26.2+)."
echo "Opcional — enlazar Mateo para spd-say:"
echo "  bash native/link-mateo-voice.sh"
echo ""
echo "Probar voz (modo directo snap, sin speech-dispatcher):"
echo "  rhvoice.test -p mateo -o ~/mateo-test.wav -i <(echo 'Prueba en español')"
echo "  ffplay -nodisp -autoexit ~/mateo-test.wav"
echo ""
echo "Probar voz (speech-dispatcher, tras link-mateo-voice.sh):"
echo "  spd-say -o rhvoice -y mateo -l es 'Prueba de voz neuronal Mateo'"
echo ""
