@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Photo album - auto start on boot
rem Puts a small file into the Windows Startup folder so start.bat runs after you log in to Windows.
rem Prefers the standard folder D:\사진저장소\server if it exists; otherwise this folder.
set "SRV=%~dp0"
if exist "D:\사진저장소\server\start.bat" set "SRV=D:\사진저장소\server\"
set "DST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\사진저장소 서버 자동시작.bat"
if exist "%DST%" (
  del "%DST%"
  echo Auto start turned OFF. (removed from the Startup folder)
) else (
  > "%DST%" echo @echo off
  >> "%DST%" echo timeout /t 20 /nobreak ^>nul
  >> "%DST%" echo start "" /min "%SRV%start.bat"
  echo Auto start turned ON for: %SRV%start.bat
  echo After you log in to Windows, the server starts by itself after 20 seconds.
)
echo Run this file again to switch it off/on.
pause
