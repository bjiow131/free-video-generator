@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Agnes Video Generator - Local Server

echo.
echo ============================================================
echo   Agnes Video Generator - Windows Local Server
echo ============================================================
echo.

REM --- Find a supported Python installation ---
set "PYTHON="
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

if not defined PYTHON (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
        if not errorlevel 1 (
            echo [1/4] Creating Python virtual environment...
            py -3 -m venv .venv
            if errorlevel 1 goto :python_error
            set "PYTHON=.venv\Scripts\python.exe"
        )
    )
)

if not defined PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
        if not errorlevel 1 (
            echo [1/4] Creating Python virtual environment...
            python -m venv .venv
            if errorlevel 1 goto :python_error
            set "PYTHON=.venv\Scripts\python.exe"
        )
    )
)

if not defined PYTHON goto :python_error

echo [2/4] Checking FFmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 goto :ffmpeg_error
ffmpeg -version >nul 2>nul
if errorlevel 1 goto :ffmpeg_error

echo [3/4] Installing/updating Python dependencies...
"%PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo [4/4] Starting local server...
echo.
echo   Web UI: http://127.0.0.1:8765
echo   Health: http://127.0.0.1:8765/health
echo.
echo   Press Ctrl+C to stop the server.
echo.

REM Open the local UI in the default browser.
start "" "http://127.0.0.1:8765"

set "HOST=127.0.0.1"
set "PORT=8765"
"%PYTHON%" server.py
set "ERR=%ERRORLEVEL%"

echo.
echo Server stopped with exit code %ERR%.
pause
exit /b %ERR%

:python_error
echo.
echo ERROR: Python 3.10 or newer is required.
echo Install Python from https://www.python.org/downloads/
echo Make sure the Python Launcher ^(py^) or python.exe is available in PATH.
echo.
pause
exit /b 1

:ffmpeg_error
echo.
echo ERROR: FFmpeg was not found in PATH.
echo Install FFmpeg and add its bin folder to PATH, then run this file again.
echo Example with winget:
echo   winget install Gyan.FFmpeg
echo.
pause
exit /b 1
