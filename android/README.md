# Narrador Android

App móvil con:

- **Navegador** integrado (WebView) para YouTube con narración de subtítulos (TTS del sistema).
- **Lector de libros**: TXT, EPUB, PDF, DOCX (y DOC limitado).

No es la extensión de Chrome empaquetada: reutiliza la misma idea (subtítulos + TTS + documentos).

## Requisitos en el PC (Fedora 44+)

En Fedora **no existe** `java-17-openjdk-devel`. Usa **Java 25** y **Gradle 9.1** (ya configurado en el proyecto):

```bash
sudo dnf install -y android-tools java-25-openjdk-devel unzip wget
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export ANDROID_HOME="$HOME/Android/Sdk"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

cd android
chmod +x setup-android.sh
./setup-android.sh
```

(`setup-android.sh` descarga el SDK si falta y compila el APK.)

## Compilar APK

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
cd android
./gradlew assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`

## Instalar en el teléfono

1. En el móvil: **Ajustes → Opciones de desarrollador → Depuración USB** (activar).
2. Conecta por USB y acepta la autorización.
3. En el PC:

```bash
adb devices
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Uso en el móvil

1. **YouTube**: pestaña inferior → abre un vídeo → activa subtítulos (CC) en el reproductor → interruptor «Narración activa».
2. **Libros**: pestaña Libros → Abrir documento → Narrar / Pausar.

### Voces en Android

Instala voces españolas del sistema:

**Ajustes → Sistema → Idiomas → Texto a voz** → motor Google → descargar **Español**.

La extensión de PC usa RHVoice/Edge; en Android se usa **TextToSpeech** (Google).

## Android Studio (opcional)

Abre la carpeta `android/` → deja que sincronice Gradle → Run en dispositivo.

## Limitaciones

- YouTube en WebView puede comportarse distinto que en Chrome de escritorio; si no carga, prueba `https://m.youtube.com`.
- `.doc` antiguo (Word 97): convierte a `.docx` en el PC.
- PDF escaneado (solo imagen): sin OCR no hay texto.
- No sustituye la app oficial de YouTube en Play Store; es un navegador con narrador.

## Enlaces desde otras apps

- Enlaces `https://youtube.com/...` → abren en la pestaña YouTube.
- PDF/EPUB/DOCX compartidos → pestaña Libros.
