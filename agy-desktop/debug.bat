@echo off
rem Starts the app WITHOUT admin relaunch and shows all errors in this window.
cd /d "%~dp0"
set AGY_NO_ADMIN=1
set ELECTRON_ENABLE_LOGGING=1
set ELECTRON_ENABLE_STACK_DUMPING=1
"%~dp0node_modules\electron\dist\electron.exe" "%~dp0." --enable-logging
echo.
echo Exit code: %errorlevel%
echo Log file: %APPDATA%\agy-desktop\agy-desktop.log
type "%APPDATA%\agy-desktop\agy-desktop.log" 2>nul
pause
