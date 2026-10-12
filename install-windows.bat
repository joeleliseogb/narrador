@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Instalador de Narrador de Libros para Windows

echo ========================================================
echo   Instalando Narrador de Libros en Windows
echo ========================================================
set "APP_DIR=%~dp0"
REM Quitar barra invertida final si existe
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo Directorio de la aplicacion: %APP_DIR%
echo.

REM 1. Verificar Python
echo [1/4] Verificando instalacion de Python...
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo ❌ Error: Python 3 no esta instalado o no se encuentra en el PATH.
        echo Por favor instala Python 3 desde https://www.python.org/downloads/
        echo IMPORTANTE: Marca la casilla "Add Python to PATH" durante la instalacion.
        pause
        exit /b 1
    ) else (
        set "PY_CMD=py"
    )
) else (
    set "PY_CMD=python"
)
for /f "tokens=*" %%v in ('%PY_CMD% --version 2^>^&1') do echo ✓ Detectado: %%v

REM 2. Instalar dependencias
echo.
echo [2/4] Instalando dependencias necesarias de Python...
%PY_CMD% -m pip install -r "%APP_DIR%\libro\requirements.txt" --quiet
if errorlevel 1 (
    echo ⚠️ Aviso: Algunos paquetes no se pudieron instalar via pip automatico.
) else (
    echo ✓ Dependencias instaladas correctamente.
)

REM 3. Crear lanzador silencioso (sin ventana de consola negra)
echo.
echo [3/4] Creando lanzadores del sistema...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo strCurDir = "%APP_DIR%"
echo WshShell.Run "pythonw.exe """ ^& strCurDir ^& "\libro\narrador-gui.py""", 0, False
) > "%APP_DIR%\narrador.vbs"

(
echo @echo off
echo start "" pythonw.exe "%APP_DIR%\libro\narrador-gui.py" %%*
) > "%APP_DIR%\narrador.cmd"
echo ✓ Lanzadores creados (narrador.vbs y narrador.cmd).

REM 4. Crear accesos directos en Menú Inicio y Escritorio
echo.
echo [4/4] Creando accesos directos en Menu Inicio y Escritorio...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$startMenu = [System.Environment]::GetFolderPath('Programs'); " ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop'); " ^
  "$appDir = '%APP_DIR%'; " ^
  "$vbs = Join-Path $appDir 'narrador.vbs'; " ^
  "$ico = Join-Path $appDir 'icons\narrador.ico'; " ^
  "$s1 = $ws.CreateShortcut((Join-Path $startMenu 'Narrador de Libros.lnk')); " ^
  "$s1.TargetPath = 'wscript.exe'; " ^
  "$s1.Arguments = '\"' + $vbs + '\"'; " ^
  "$s1.WorkingDirectory = $appDir; " ^
  "if (Test-Path $ico) { $s1.IconLocation = $ico }; " ^
  "$s1.Description = 'Narrador de Libros y Audiolibros MP3'; " ^
  "$s1.Save(); " ^
  "$s2 = $ws.CreateShortcut((Join-Path $desktop 'Narrador de Libros.lnk')); " ^
  "$s2.TargetPath = 'wscript.exe'; " ^
  "$s2.Arguments = '\"' + $vbs + '\"'; " ^
  "$s2.WorkingDirectory = $appDir; " ^
  "if (Test-Path $ico) { $s2.IconLocation = $ico }; " ^
  "$s2.Description = 'Narrador de Libros y Audiolibros MP3'; " ^
  "$s2.Save();"

echo.
echo ========================================================
echo 🎉 ¡Instalación en Windows completada con éxito!
echo ========================================================
echo • Se ha agregado al Menú Inicio como "Narrador de Libros".
echo • Se ha creado un acceso directo en tu Escritorio.
echo • Puedes abrirlo haciendo doble clic en el acceso directo.
echo ========================================================
echo.
pause
