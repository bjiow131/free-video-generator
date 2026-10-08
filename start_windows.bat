@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Agnes Video Generator - Local Server

echo.
echo ==========================================
echo   AGNES VIDEO GENERATOR
echo ==========================================
echo.

REM --- Agnes API key must come from Windows environment ---
if "%AGNES_API_KEY%"=="" (
    echo [ERROR] AGNES_API_KEY not found.
    echo.
    echo Run this once in a CMD window:
    echo.
    echo   setx AGNES_API_KEY "YOUR_AGNES_KEY"
    echo.
    echo Then close CMD completely and run this BAT again.
    echo.
    pause
    exit /b 1
)

echo Agnes API key found.
echo.

REM --- Python virtual environment ---
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found:
    echo %~dp0.venv
    echo.
    echo Create it with:
    echo   py -3 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM --- FFmpeg ---
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [ERROR] FFmpeg was not found in PATH.
    echo Install FFmpeg and add it to PATH.
    echo.
    pause
    exit /b 1
)

echo Starting Agnes Video Generator...
echo.

REM --- Start the local server ---
start "" /b ".venv\Scripts\python.exe" server.py

echo Waiting for Agnes Video Generator...

:wait
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8765/health >nul 2>&1
if errorlevel 1 goto wait

echo.
echo Agnes Video Generator is running!
echo http://127.0.0.1:8765
echo.

REM --- Open Chrome without GPU when available ---
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo Opening Google Chrome without GPU...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --disable-gpu http://127.0.0.1:8765
) else (
    echo Chrome was not found at the standard path.
    echo Opening the default browser...
    start "" http://127.0.0.1:8765
)

echo.
echo ==========================================
echo   Agnes Video Generator is running!
echo ==========================================
echo.
echo Local server: http://127.0.0.1:8765
echo Agnes: API key loaded from Windows environment
echo.
echo Close the Python server window or press Ctrl+C
echo in the server console to stop the server.
echo.
pause
