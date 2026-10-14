@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Agnes Video Generator - Local Setup

echo.
echo ==========================================
echo   AGNES VIDEO GENERATOR - SETUP
echo ==========================================
echo.

REM --- Python ---
where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher (py.exe) was not found.
    echo Install Python 3.10 or newer and enable the Python Launcher.
    echo Then reopen this terminal and run setup_windows.bat again.
    echo.
    pause
    exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required.
    py -3 --version
    echo.
    pause
    exit /b 1
)

REM --- FFmpeg and ffprobe ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [ERROR] FFmpeg was not found in PATH.
    echo Install FFmpeg, add its bin folder to PATH, reopen the terminal,
    echo and run setup_windows.bat again.
    echo.
    pause
    exit /b 1
)

where ffprobe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] ffprobe was not found in PATH.
    echo Install the FFmpeg package that includes ffprobe, add its bin folder
    echo to PATH, reopen the terminal, and run setup_windows.bat again.
    echo.
    pause
    exit /b 1
)

REM --- Create an isolated project environment only if missing ---
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto setup_failed
)

echo Installing project dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

echo.
echo Setup completed.
echo Next step: run start_windows.bat
echo.
pause
exit /b 0

:setup_failed
echo.
echo [ERROR] Setup failed. Review the error above, fix the cause, and rerun setup_windows.bat.
echo The script does not delete your existing environment or project data.
echo.
pause
exit /b 1
