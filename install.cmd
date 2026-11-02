@echo off
rem STELLA CODER + Vibing AI Studio installer (double-click or run from cmd).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 pause
