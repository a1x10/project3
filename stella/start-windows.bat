@echo off
chcp 65001 >nul
title Stella Assistant
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo [!] Не найден Node.js. Установите его с https://nodejs.org ^(версия LTS^), затем запустите этот файл снова.
  start https://nodejs.org
  pause
  exit /b 1
)
if not exist node_modules (
  echo Первый запуск: устанавливаю зависимости ^(1-3 минуты^)...
  call npm install
  if errorlevel 1 ( echo [!] Ошибка установки. & pause & exit /b 1 )
)
call npm start
