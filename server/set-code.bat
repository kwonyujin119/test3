@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Photo album access code
rem Sets the access code of the photo album. Stored in data\config.json as a hash only.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)
if not exist album_server.py (
  echo [ERROR] Put this file in the album server folder next to album_server.py.
  pause
  exit /b 1
)
echo.
echo Type the new access code (4 characters or more) and press Enter.
echo.
set "CODE="
set /p CODE=Code:
%PY% album_server.py --set-code "%CODE%"
set "CODE="
pause
