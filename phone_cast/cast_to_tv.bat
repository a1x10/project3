@echo off
chcp 65001 >nul
REM Поменяй "Xiaomi TV" на имя своего телевизора (как оно видно в списке трансляции)
python "%~dp0cast_to_tv.py" --tv "Xiaomi TV" %*
pause
