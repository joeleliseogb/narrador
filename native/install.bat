@echo off
:: Instala el host nativo para Brave, Chrome y Microsoft Edge en Windows.
chcp 65001 >nul

setlocal enabledelayedexpansion

:: Asegura que el directorio es el del script
cd /d "%~dp0"
set "SCRIPT_DIR=%cd%"
set "HOST_PY=%SCRIPT_DIR%\narrador-host.py"
set "APP_DATA_DIR=%APPDATA%\Narrador"
set "LAUNCHER=%APP_DATA_DIR%\narrador-youtube-tts.bat"
set "MANIFEST=%APP_DATA_DIR%\com.narrador.youtube.json"
set "HOST_ID=com.narrador.youtube"

set "CHROMIUM_ID=%~1"
set "EDGE_ID=%~2"

if "%CHROMIUM_ID%"=="" (
    echo === Instalador del motor de voz nativo (Windows) ===
    echo.
    echo Necesitas el ID de la extensión en cada navegador donde la uses.
    echo   Brave:  brave://extensions/
    echo   Chrome: chrome://extensions/
    echo   Edge:   edge://extensions/
    echo   (Modo desarrollador activado - copiar ID)
    echo.
    set /p "CHROMIUM_ID=ID Brave / Chrome / Chromium: "
    
    if "!CHROMIUM_ID!"=="" (
        set /p "CHROMIUM_ID=¿Solo Microsoft Edge? Pega el ID de Edge: "
    )
    
    if "!CHROMIUM_ID!"=="" (
        echo Error: hace falta al menos un ID.
        pause
        exit /b 1
    )
    
    echo.
    set /p "EDGE_ANSWER=ID de Edge (Enter = mismo ID; escribe 'no' para omitir Edge): "
    if "!EDGE_ANSWER!"=="" (
        set "EDGE_ID=!CHROMIUM_ID!"
    ) else if /i not "!EDGE_ANSWER!"=="no" if /i not "!EDGE_ANSWER!"=="n" (
        set "EDGE_ID=!EDGE_ANSWER!"
    )
) else (
    if "%EDGE_ID%"=="" (
        set "EDGE_ID=%CHROMIUM_ID%"
    ) else if /i "%EDGE_ID%"=="no" (
        set "EDGE_ID="
    ) else if /i "%EDGE_ID%"=="n" (
        set "EDGE_ID="
    )
)

echo.
echo Creando directorios y archivos de inicio...
if not exist "%APP_DATA_DIR%" mkdir "%APP_DATA_DIR%"

:: Crear launcher por lotes para lanzar Python sin abrir ventana negra de cmd si es posible (usando pythonw)
(
echo @echo off
echo where pythonw >nul 2>nul
echo if %%ERRORLEVEL%% equ 0 (
echo     start "" /b pythonw "%HOST_PY%"
echo ) else (
echo     python "%HOST_PY%"
echo )
) > "%LAUNCHER%"

:: Generar Manifiesto JSON
(
echo {
echo   "name": "%HOST_ID%",
echo   "description": "Narrador YouTube TTS host",
echo   "path": "%LAUNCHER:\=\\%",
echo   "type": "stdio",
echo   "allowed_origins": [
echo     "chrome-extension://%CHROMIUM_ID%/"
echo   ]
echo }
) > "%MANIFEST%"

echo   ✓ %MANIFEST%

echo.
echo Registrando host en el Registro de Windows...

if not "%CHROMIUM_ID%"=="" (
    echo Navegadores Chromium (Brave / Chrome):
    reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_ID%" /ve /t REG_SZ /d "%MANIFEST%" /f >nul
    echo   ✓ Google Chrome registrado.
    reg add "HKCU\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\%HOST_ID%" /ve /t REG_SZ /d "%MANIFEST%" /f >nul
    echo   ✓ Brave Browser registrado.
)

if not "%EDGE_ID%"=="" (
    echo Microsoft Edge:
    reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\%HOST_ID%" /ve /t REG_SZ /d "%MANIFEST%" /f >nul
    echo   ✓ Microsoft Edge registrado.
)

echo.
echo Listo. Recarga la extensión en cada navegador y prueba en YouTube.
echo.
pause
