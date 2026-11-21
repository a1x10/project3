@echo off
chcp 65001 >nul
title Agy Desktop - установка
cd /d "%~dp0"

echo.
echo  === Agy Desktop: установка ===
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo  [1/3] Node.js не найден - устанавливаю через winget...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  set "PATH=%PATH%;%ProgramFiles%\nodejs"
) else (
  echo  [1/3] Node.js найден
)

where node >nul 2>nul
if errorlevel 1 (
  echo  Не удалось найти Node.js. Установите его с https://nodejs.org и запустите install.bat ещё раз.
  pause
  exit /b 1
)

echo  [2/3] Устанавливаю зависимости...
call npm install --no-audit --no-fund
if errorlevel 1 (
  echo  Ошибка npm install
  pause
  exit /b 1
)

echo  [3/3] Создаю ярлыки (всегда от имени администратора)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make-shortcut.ps1" -AppDir "%~dp0."

echo.
echo  Готово! Запускаю Agy Desktop...
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
timeout /t 3 >nul
