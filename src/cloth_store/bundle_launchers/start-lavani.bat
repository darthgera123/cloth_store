@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=py -3"
    goto :serve
)

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=python"
    goto :serve
)

echo.
echo Python 3 is not installed or not on PATH.
echo Install from https://www.python.org/downloads/
echo During setup, check "Add python.exe to PATH".
echo.
pause
exit /b 1

:serve
echo.
echo Lavani's Closet - local preview at http://127.0.0.1:8080/
echo Press Ctrl+C to stop the server.
echo.
start "" "http://127.0.0.1:8080/"
%PYTHON% -m http.server 8080 --bind 127.0.0.1
echo.
pause
