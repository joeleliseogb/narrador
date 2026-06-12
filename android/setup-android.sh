#!/usr/bin/env bash
# Fedora 44+: Java 17 no está en repos; usa Java 25 + Gradle 9.1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_ROOT="${ANDROID_HOME:-$HOME/Android/Sdk}"
CMD_TOOLS="$SDK_ROOT/cmdline-tools/latest"
BIN_SDKMANAGER="$CMD_TOOLS/bin/sdkmanager"

echo "=== Narrador Android — instalación (Fedora) ==="
echo "SDK: $SDK_ROOT"
echo ""

# Java 25 (único JDK estable en Fedora 44 en repos oficiales)
if [[ -d /usr/lib/jvm/java-25-openjdk ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
elif [[ -d /usr/lib/jvm/java-openjdk ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-openjdk
else
  echo "Instala JDK: sudo dnf install -y java-25-openjdk-devel"
  exit 1
fi
export PATH="$JAVA_HOME/bin:$PATH"
echo "JAVA_HOME=$JAVA_HOME"
java -version

if command -v dnf >/dev/null 2>&1; then
  echo ""
  echo "Paquetes (sudo)…"
  sudo dnf install -y android-tools java-25-openjdk-devel unzip wget
fi

mkdir -p "$SDK_ROOT"

if [[ ! -x "$BIN_SDKMANAGER" ]]; then
  echo "Descargando Android command-line tools…"
  TMP="$(mktemp -d)"
  ZIP_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
  wget -q -O "$TMP/cmdline.zip" "$ZIP_URL"
  unzip -q "$TMP/cmdline.zip" -d "$TMP"
  mkdir -p "$SDK_ROOT/cmdline-tools"
  rm -rf "$CMD_TOOLS"
  mv "$TMP/cmdline-tools" "$CMD_TOOLS"
  rm -rf "$TMP"
fi

export ANDROID_HOME="$SDK_ROOT"
export PATH="$CMD_TOOLS/bin:$SDK_ROOT/platform-tools:$PATH"

echo "Aceptando licencias SDK…"
yes | sdkmanager --licenses >/dev/null 2>&1 || yes | sdkmanager --licenses

echo "Instalando plataforma y build-tools…"
sdkmanager \
  "platform-tools" \
  "platforms;android-35" \
  "build-tools;35.0.0"

echo "sdk.dir=$SDK_ROOT" > "$ROOT/local.properties"

chmod +x "$ROOT/gradlew" 2>/dev/null || true

echo ""
echo "Compilando APK (Gradle 9.1 + Java 25)…"
cd "$ROOT"
./gradlew assembleDebug

APK="$ROOT/app/build/outputs/apk/debug/app-debug.apk"
echo ""
echo "=== Listo ==="
echo "APK: $APK"
echo ""
echo "Instalar en el móvil:"
echo "  adb install -r \"$APK\""
