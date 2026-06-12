#!/usr/bin/env bash
# Instala herramientas Android en Fedora/Linux para compilar Narrador móvil.
set -euo pipefail

SDK_ROOT="${ANDROID_HOME:-$HOME/Android/Sdk}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD_TOOLS="$SDK_ROOT/cmdline-tools/latest"
CHANNEL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

echo "=== Narrador Android — instalación del SDK ==="
echo "SDK: $SDK_ROOT"
echo ""

if [[ -d /usr/lib/jvm/java-25-openjdk ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
  export PATH="$JAVA_HOME/bin:$PATH"
elif [[ -d /usr/lib/jvm/java-openjdk ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-openjdk
  export PATH="$JAVA_HOME/bin:$PATH"
fi

if command -v dnf >/dev/null 2>&1; then
  echo "Paquetes del sistema (sudo):"
  echo "  sudo dnf install -y android-tools java-25-openjdk-devel unzip wget"
fi

mkdir -p "$SDK_ROOT/cmdline-tools"
export ANDROID_HOME="$SDK_ROOT"
export PATH="$SDK_ROOT/platform-tools:$CMD_TOOLS/bin:$PATH"

if [[ ! -x "$CMD_TOOLS/bin/sdkmanager" ]]; then
  echo "Descargando Android command-line tools…"
  TMP="$(mktemp -d)"
  wget -q -O "$TMP/cmdtools.zip" "$CHANNEL"
  unzip -q "$TMP/cmdtools.zip" -d "$TMP"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"
  mv "$TMP/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
  rm -rf "$TMP"
fi

yes | sdkmanager --licenses >/dev/null 2>&1 || true
sdkmanager \
  "platform-tools" \
  "platforms;android-35" \
  "build-tools;35.0.0"

cat > "$SCRIPT_DIR/local.properties" <<EOF
sdk.dir=$SDK_ROOT
EOF

if [[ ! -f "$SCRIPT_DIR/gradlew" ]]; then
  echo "Generando Gradle Wrapper…"
  if command -v gradle >/dev/null 2>&1; then
    (cd "$SCRIPT_DIR" && gradle wrapper --gradle-version 9.1.0)
  else
    echo "Instala Gradle para generar gradlew: sudo dnf install gradle"
    echo "O abre la carpeta android/ en Android Studio (creará el wrapper)."
  fi
fi

echo ""
echo "Listo."
echo "  export ANDROID_HOME=$SDK_ROOT"
echo "  export PATH=\$ANDROID_HOME/platform-tools:\$PATH"
echo ""
echo "Compilar APK debug:"
echo "  cd \"$SCRIPT_DIR\""
echo "  ./gradlew assembleDebug"
echo ""
echo "Instalar en el móvil (USB + depuración):"
echo "  adb install -r app/build/outputs/apk/debug/app-debug.apk"
