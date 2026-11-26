@echo off
rem Doble clic para armar "RKB Collection Manager.exe" (queda en Descargas).
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0armar_app_windows.ps1"
echo.
pause
