@echo off
chcp 65001 >nul
cd /d "%~dp0"
where node >nul 2>nul || (echo Установите Node.js 20+ с https://nodejs.org и запустите снова & pause & exit /b 1)
if not exist node_modules call npm install --omit=dev
node launch.js
pause
