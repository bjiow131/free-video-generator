@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv. Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
)

echo [2/3] Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo [3/3] Starting AI Studio on http://localhost:8765
".venv\Scripts\python.exe" server.py
set ERR=%ERRORLEVEL%

echo.
echo Server stopped with exit code %ERR%.
pause
exit /b %ERR%
