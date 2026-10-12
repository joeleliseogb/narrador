# 🚀 Instaladores de Narrador de Libros

Esta carpeta y los scripts de la raíz te permiten instalar **Narrador de Libros** de forma permanente en tu sistema operativo (**GNU/Linux**, **Windows** y **macOS**), agregándolo directamente a tu **lista de programas / Menú de Aplicaciones / Spotlight / Menú Inicio**, con icono oficial, asociaciones de archivos y comando de terminal directo.

---

## 🐧 GNU / Linux

### Instalación:
Ejecuta en una terminal dentro de la carpeta del proyecto:
```bash
./install-linux.sh
```

**¿Qué hace?**
1. Instala el acceso directo en `~/.local/share/applications/narrador.desktop`.
2. Asocia la aplicación a los tipos de archivo PDF, EPUB, TXT, Word (.docx) y ODT.
3. Copia los iconos en alta resolución en el tema de iconos de tu sistema (`~/.local/share/icons/hicolor/`).
4. Crea el comando `narrador` en `~/.local/bin/narrador` para que puedas abrirlo desde cualquier terminal.
5. Aparece de inmediato en tu **Menú de Aplicaciones** (GNOME, KDE, XFCE, Cinnamon, etc.).

### Desinstalación:
```bash
./uninstall-linux.sh
```

---

## 🪟 Windows (10 y 11)

### Instalación:
Haz **doble clic** sobre el archivo:
```
install-windows.bat
```
*(O ejecútalo desde PowerShell / CMD).*

**¿Qué hace?**
1. Verifica que tengas Python 3 instalado.
2. Instala automáticamente las librerías necesarias (`requirements.txt`).
3. Genera un lanzador silencioso (`narrador.vbs`) para que la aplicación abra limpia **sin dejar una consola negra abierta de fondo**.
4. Crea un acceso directo en tu **Menú Inicio** (`Narrador de Libros`).
5. Crea un acceso directo en tu **Escritorio** con el icono `.ico` oficial.
6. Permite invocarlo desde la consola con `narrador.cmd`.

### Desinstalación:
Haz doble clic sobre:
```
uninstall-windows.bat
```

---

## 🍏 macOS (Intel & Apple Silicon M1/M2/M3/M4)

### Instalación:
Haz **doble clic** sobre el archivo en el Finder:
```
install-macos.command
```
*(O ejecútalo en la terminal con `./install-macos.command` o `./install-macos.sh`).*

**¿Qué hace?**
1. Crea el paquete de aplicación nativo `Narrador.app` en tu carpeta `~/Applications/` (o `/Applications/`).
2. Configura los metadatos `Info.plist` con soporte para pantallas Retina (HiDPI).
3. Genera el icono de alta resolución `narrador.icns` usando las herramientas nativas de macOS (`sips` e `iconutil`).
4. Registra la aplicación en **Launchpad**, **Spotlight** y **Dock** mediante *Launch Services*.
5. Crea el alias de consola `narrador` en `~/.local/bin/narrador`.

### Desinstalación:
Haz doble clic sobre:
```
uninstall-macos.command
```

---

## 📦 Compilación a Binarios Autónomos (Opcional - Standalone)

Si deseas empaquetar todo el proyecto en un ejecutable independiente (sin requerir Python en la máquina de destino):
```bash
python3 installers/build_standalone.py
```
El archivo compilado se generará dentro de la carpeta `dist/Narrador`.
