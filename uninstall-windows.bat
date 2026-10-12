@echo off
chcp 65001 >nul
title Desinstalador de Narrador de Libros para Windows

echo ========================================================
echo   Desinstalando Narrador de Libros de Windows
echo ========================================================
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$startMenu = [System.Environment]::GetFolderPath('Programs'); " ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop'); " ^
  "$lnk1 = Join-Path $startMenu 'Narrador de Libros.lnk'; " ^
  "$lnk2 = Join-Path $desktop 'Narrador de Libros.lnk'; " ^
  "if (Test-Path $lnk1) { Remove-Item $lnk1 -Force; Write-Host '✓ Eliminado acceso del Menú Inicio' }; " ^
  "if (Test-Path $lnk2) { Remove-Item $lnk2 -Force; Write-Host '✓ Eliminado acceso del Escritorio' };"

if exist "%APP_DIR%\narrador.vbs" del "%APP_DIR%\narrador.vbs"
if exist "%APP_DIR%\narrador.cmd" del "%APP_DIR%\narrador.cmd"

echo ✓ Lanzadores eliminados.
echo ========================================================
echo ✓ Narrador de Libros ha sido desinstalado de Windows.
echo ========================================================
echo.
pause
