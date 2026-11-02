@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Photo album - fix and start
rem One click: stop old album servers, gather photos/list from every album folder on this PC into D:\사진저장소,
rem put the newest files there and start the server. Nothing is deleted.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix.ps1"
echo.
pause
