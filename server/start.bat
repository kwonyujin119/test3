@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set ALBUM_LOOP=1
title Yujin-Areum photo album server (auto update)
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python not found. Install Python 3 from https://www.python.org/downloads/
  echo         and check "Add python.exe to PATH" during install.
  pause
  exit /b 1
)
set /a FAILS=0
:run
%PY% album_server.py
set "RC=%errorlevel%"
rem 75 = the server downloaded a new version of itself: start again right away
if "%RC%"=="75" (
  set /a FAILS=0
  echo [update] Restarting with the new server file ...
  goto run
)
rem The new file stopped within its first minute: put the previous file back and start again
if exist data\update_verify.flag (
  if exist album_server.py.bak (
    echo [update] The new server file stopped. Restoring the previous file ...
    copy /y album_server.py.bak album_server.py >nul
    del data\update_verify.flag
    goto run
  )
)
if not "%RC%"=="0" (
  set /a FAILS+=1
  if %FAILS% GEQ 5 (
    echo [ERROR] The server stopped 5 times in a row ^(code %RC%^). Check the messages above, then run this file again.
    pause
    exit /b 1
  )
  echo [restart] The server stopped ^(code %RC%^). Starting again in 20 seconds ... ^(%FAILS%/5^)
  timeout /t 20 /nobreak >nul
  goto run
)
pause
