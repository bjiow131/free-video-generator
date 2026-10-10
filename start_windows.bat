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

REM --- Agnes API key is optional here; it may be configured in the Web UI ---
if "%AGNES_API_KEY%"=="" (
    echo [WARNING] AGNES_API_KEY is not set in Windows.
    echo The server will still start. You can configure the API key in the Web UI.
    echo.
) else (
    echo Agnes API key found.
    echo.
)

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

REM --- Bounded readiness check: do not wait forever if startup fails ---
echo Waiting for Agnes Video Generator (maximum 60 seconds)...
set "WAIT_ATTEMPTS=0"

:wait
timeout /t 2 /nobreak >nul
curl -fsS --max-time 2 http://127.0.0.1:8765/health >nul 2>&1
if not errorlevel 1 goto server_ready

set /a WAIT_ATTEMPTS+=1
if %WAIT_ATTEMPTS% GEQ 30 goto startup_failed
goto wait

:startup_failed
echo.
echo [ERROR] The server did not become ready within 60 seconds.
echo Check the Python error output above and verify port 8765 is available.
echo If the Python process is still running, stop it before trying again.
echo.
pause
exit /b 1

:server_ready
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
echo Agnes: API key loaded from Windows environment or local UI config
echo.
echo Close the Python server process or press Ctrl+C
echo in its console to stop the server.
echo.
pause
