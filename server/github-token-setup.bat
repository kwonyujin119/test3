@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Photo album - GitHub token setup
rem Saves a GitHub token into data\config.json. The server uses it ONLY to write its public address
rem into server-url.json of the test3 repository, so the page at kwonyujin119.github.io/test3 can find the server.
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
echo Paste the GitHub token (starts with github_pat_ or ghp_) and press Enter.
echo How to make one: github.com - Settings - Developer settings - Personal access tokens
echo   - Fine-grained tokens - Generate new token - Repository access: Only select repositories: test3
echo   - Permissions: Contents = Read and write - Generate token - Copy
echo.
set "TOKEN="
set /p TOKEN=Token:
%PY% album_server.py --set-github-token "%TOKEN%"
set "TOKEN="
pause
