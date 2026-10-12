# Narrador de Subtítulos YouTube (+ libros)

Extensión para **YouTube** que narra subtítulos con voz neuronal (RHVoice local o Microsoft Edge TTS). Incluye un **lector de libros** en línea de comandos (TXT / EPUB).

## Android (app móvil)

App nativa con navegador (YouTube + webs), narración de subtítulos, libros (TXT/EPUB/PDF/DOCX) y multimedia.

```bash
cd android && chmod +x setup-android.sh && ./setup-android.sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Detalles: [android/README.md](android/README.md)

## Navegadores (extensión escritorio)

| Navegador | Soporte |
|-----------|---------|
| **Brave** | Sí |
| **Google Chrome** | Sí |
| **Microsoft Edge** | Sí (cargar extensión + ID distinto en `native/install.sh`) |
| **Firefox** | No (por ahora) |
| **Android** | App en `android/` (WebView + lector de libros) |
| **Android / iOS** | App Android sí; extensión en móvil no |

## Instalación extensión

1. Abre `brave://extensions/`, `chrome://extensions/` o `edge://extensions/`
2. Activa **Modo de desarrollador** (arriba a la derecha)
3. Pulsa **Cargar descomprimida**
4. Selecciona la carpeta `Narrador`
5. Abre un vídeo en YouTube y activa los subtítulos (CC) si no se activan solos
6. Haz clic en el icono de la extensión para ajustar voz, velocidad y volumen

## Uso

1. Abre cualquier vídeo en YouTube
2. La extensión intentará activar los subtítulos automáticamente (configurable)
3. Cuando aparezcan subtítulos en pantalla, los leerá en voz alta
4. La narración se pausa cuando pausas el vídeo

## Configuración

| Opción | Descripción |
|--------|-------------|
| Activar narración | Enciende o apaga la lectura de subtítulos |
| Idioma de voz | Idioma para la síntesis de voz |
| Voz | Voz específica del sistema (depende del SO) |
| Velocidad | Rapidez de la narración (0.5x – 2x) |
| Tono | Tono de la voz |
| Volumen | Volumen de la narración |
| Activar subtítulos automáticamente | Pulsa el botón CC de YouTube al cargar un vídeo |

## Requisitos

- Google Chrome o Chromium
- Subtítulos disponibles en el vídeo (automáticos o manuales)
- Voces del sistema instaladas (en Linux: `speech-dispatcher`, `espeak` o voces de Google)

### Voces en Linux (Fedora/Ubuntu)

```bash
# Fedora
sudo dnf install espeak-ng speech-dispatcher

# Ubuntu/Debian
sudo apt install speech-dispatcher espeak-ng
```

Reinicia el navegador después de instalar voces adicionales.

### Motor nativo (Linux / Brave)

En Linux la extensión usa `spd-say` del sistema. Instala el host nativo una vez:

```bash
chmod +x native/install.sh
./native/install.sh
```

El instalador registra el host en **Brave, Chrome, Chromium y Edge** (también rutas Flatpak). Pide el ID de Brave/Chrome y, si usas Edge, el ID de `edge://extensions/` (suele ser distinto).

### Voces neuronales en español (RHVoice)

Las voces por defecto (`espeak-ng`) suenan robóticas. Para voz **neuronal en español**:

```bash
# Desde la carpeta del proyecto:
cd "/home/joel/Documentos/Code APP/Narrador"
./native/install-rhvoice.sh

# O manualmente (Snap + voces):
sudo snap install rhvoice
sudo rhvoice.vm -a                    # listar voces (busca span/espa)
sudo rhvoice.vm -i mateo                # instalar Mateo (español latino)
sudo rhvoice.vm -l                    # comprobar instaladas
sudo ln -sf /snap/rhvoice/current/bin/sd_rhvoice /usr/lib64/speech-dispatcher-modules/sd_rhvoice
systemctl --user restart speech-dispatcher
```

Voces en español: [RHVoice/spanish-bin](https://github.com/RHVoice/spanish-bin) (castellano y latino neutro).

Tras instalar, reinicia Brave y elige la voz RHVoice en el selector **Voz** del popup.

## Notas

- Descarga subtítulos con tiempos y narra sincronizado con el vídeo
- Volumen, tono y velocidad funcionan con el motor nativo (`spd-say`)
- Solo funciona en páginas de YouTube (`youtube.com`)

## Narrador de libros y Audiolibros MP3 (PDF / EPUB / TXT / Word / ODT)

### Aplicación con Interfaz Gráfica (GUI)
Abre la aplicación visual con un clic:
- Desde el popup de la extensión de Chrome: botón **«📖 Lector de Libros & Audiolibros MP3»**.
- O desde el terminal / doble clic:
  ```bash
  ./narrador-libros.sh
  ```
- O buscándola en tu menú de aplicaciones: **«Narrador de Libros & Audiolibros»**.

Te permite ver los capítulos, páginas, escuchar con resalte visual y **crear archivos de audiolibro en MP3**.

### Desde la Terminal (CLI)
```bash
python3 libro/narrador-libro.py mi-libro.pdf --engine local --voice local:mateo
```

Detalles completos: [libro/README.md](libro/README.md)

## App Android

Navegador con YouTube + lector de documentos (TXT, EPUB, PDF, DOCX):

```bash
sudo dnf install -y android-tools java-25-openjdk-devel
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
cd android && chmod +x setup-android.sh && ./setup-android.sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Guía completa: [android/README.md](android/README.md)
