@echo off
setlocal
title Stella - install
cd /d "%~dp0"

echo.
echo  === Stella: install ===
echo  Folder: %CD%
echo.

if not exist "%~dp0package.json" (
  echo  ERROR: package.json not found. Extract the ZIP archive first, then run install.bat from the extracted folder.
  pause
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo  [1/4] Node.js not found - installing with winget...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  set "PATH=%PATH%;%ProgramFiles%\nodejs"
) else (
  echo  [1/4] Node.js found
)

where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo  ERROR: Node.js still not found.
  echo  Install Node.js LTS from https://nodejs.org , then run install.bat again.
  pause
  exit /b 1
)
node -v

echo  [2/4] Installing dependencies (npm install)...
call npm install --no-audit --no-fund
if errorlevel 1 (
  echo.
  echo  ERROR: npm install failed. See messages above.
  pause
  exit /b 1
)

echo  [3/4] Checking Electron...
if not exist "%~dp0node_modules\electron\dist\electron.exe" (
  echo  electron.exe missing - downloading again...
  node "%~dp0node_modules\electron\install.js"
)
if not exist "%~dp0node_modules\electron\dist\electron.exe" (
  echo  ERROR: Electron did not download. Check internet / antivirus and run install.bat again.
  pause
  exit /b 1
)

echo  [4/4] Creating shortcuts (always run as administrator)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make-shortcut.ps1" -AppDir "%~dp0."

echo.
echo  Done! Starting Stella...
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
timeout /t 3 >nul
