#!/usr/bin/env bash
# Instala RHVoice con voces en español (Fedora).
# Ejecutar: chmod +x native/install-rhvoice.sh && ./native/install-rhvoice.sh

set -euo pipefail

echo "============================================"
echo "  Instalación RHVoice — español (Fedora)"
echo "============================================"
echo ""

if ! command -v dnf &>/dev/null; then
  echo "Este script está pensado para Fedora (dnf)."
  exit 1
fi

echo "Paso 1/5: Habilitar repositorio COPR de RHVoice..."
sudo dnf copr enable -y cuintle/RHVoice || {
  echo "Si falla, prueba: sudo dnf copr enable cuintle/RHVoice"
  exit 1
}

echo ""
echo "Paso 2/5: Instalar RHVoice y plugin de speech-dispatcher..."
sudo dnf install -y rhvoice rhvoice-speech-dispatcher-plugin rhvoice-utils

echo ""
echo "Paso 3/5: Comprobar módulos de speech-dispatcher..."
spd-say -O 2>/dev/null | grep -i rhvoice || echo "(RHVoice aparecerá tras instalar voces)"

echo ""
echo "Paso 4/5: Voces en español"
echo ""
echo "Fedora COPR no incluye paquete español oficial todavía."
echo "Opciones:"
echo ""
echo "  A) Snap (recomendado, más sencillo):"
echo "     sudo snap install rhvoice"
echo "     sudo rhvoice.vm -a                    # ver voces disponibles"
echo "     sudo rhvoice.vm -i mateo                 # voz español masculina (Mateo)"
echo "     (Leticia en RHVoice es portugués brasileño, no español — usa Edge/Elvira en el popup)"
echo "     sudo rhvoice.vm -l                    # voces instaladas"
echo ""
echo "  B) Compilar voces desde GitHub:"
echo "     https://github.com/RHVoice/spanish-bin"
echo ""
read -rp "¿Instalar RHVoice via Snap ahora? [s/N]: " DO_SNAP

if [[ "${DO_SNAP,,}" == "s" ]]; then
  if command -v snap &>/dev/null; then
    sudo snap install rhvoice
    echo ""
    echo "Voces disponibles (busca nombres con span/espa):"
    sudo rhvoice.vm -a 2>/dev/null | grep -iE 'span|espa' || sudo rhvoice.vm -a 2>/dev/null || true
    echo ""
    echo "Instala la voz Mateo (español):"
    echo "  sudo rhvoice.vm -i mateo"
    echo "  sudo rhvoice.vm -l"
    echo ""
    read -rp "¿Instalar voz 'mateo' ahora? [s/N]: " DO_VOICE
    if [[ "${DO_VOICE,,}" == "s" ]]; then
      sudo rhvoice.vm -i mateo || {
        echo "Si falla, prueba el ID exacto de: sudo rhvoice.vm -a"
      }
    fi
  else
    echo "Snap no instalado. Instala con: sudo dnf install snapd"
  fi
fi

echo ""
echo "Paso 5/5: Activar RHVoice en speech-dispatcher..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$SCRIPT_DIR/configure-rhvoice-spd.sh" ]]; then
  bash "$SCRIPT_DIR/configure-rhvoice-spd.sh"
else
  echo "Ejecuta: bash native/configure-rhvoice-spd.sh"
fi

echo ""
echo "============================================"
echo "  Listo"
echo "============================================"
echo ""
echo "1. Cierra Brave por completo y ábrelo de nuevo"
echo "2. Recarga la extensión Narrador"
echo "3. Abre el popup → selector Voz → elige voz RHVoice/español"
echo ""
echo "Probar en terminal:"
echo "  spd-say -l es -y 'RHVoice+...' 'Prueba de voz neuronal'"
echo "  spd-say -L | grep -i span"
echo ""
