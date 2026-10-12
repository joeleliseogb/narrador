#!/usr/bin/env bash
"""
Constructor de Ejecutables Autónomos (Standalone) con PyInstaller
Permite compilar 'Narrador de Libros' en un ejecutable único sin requerir
que el usuario final tenga Python instalado.

Uso:
    python3 installers/build_standalone.py
"""

from __future__ import annotations
import sys
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def build():
    print("=" * 60)
    print("  Compilando Narrador de Libros a Binario Autónomo")
    print("=" * 60)

    # 1. Comprobar o instalar pyinstaller
    try:
        import PyInstaller
    except ImportError:
        print("📦 PyInstaller no encontrado. Instalando temporalmente...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"])

    # 2. Definir rutas y assets
    main_script = ROOT / "libro" / "narrador-gui.py"
    dist_dir = ROOT / "dist"
    build_dir = ROOT / "build"
    icon_path = ROOT / "icons" / "narrador.ico" if sys.platform == "win32" else ROOT / "icons" / "icon128.png"

    # Preparar parámetros de pyinstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",                 # Sin consola negra
        "--name", "Narrador",
        f"--add-data={ROOT / 'icons'}:icons",
        f"--add-data={ROOT / 'libro'}:libro",
        f"--add-data={ROOT / 'native'}:native",
    ]

    if icon_path.exists():
        cmd.append(f"--icon={icon_path}")

    # Separador de add-data según plataforma
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        c.replace(":", sep) if c.startswith("--add-data=") and sys.platform == "win32" else c
        for c in cmd
    ]

    cmd.append(str(main_script))

    print(f"🚀 Ejecutando PyInstaller...")
    subprocess.check_call(cmd, cwd=str(ROOT))

    print("=" * 60)
    print(f"🎉 Compilación finalizada.")
    print(f"El ejecutable se encuentra en: {dist_dir / 'Narrador'}")
    print("=" * 60)

if __name__ == "__main__":
    build()
