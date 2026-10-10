@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

title Blender Work Agent - Setup
set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\venv"
set "BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

echo.
echo ==========================================
echo   BLENDER WORK AGENT - LOCAL SETUP
echo ==========================================
echo.
echo This setup installs a local-only Blender helper.
echo No GitHub token, mailbox, remote polling, or ChatGPT connection is used.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python Launcher was not found.
  echo Install Python 3.11 and rerun this script.
  pause
  exit /b 1
)

py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.11 or newer is required.
  py -3.11 --version
  pause
  exit /b 1
)

if not exist "%BLENDER_EXECUTABLE%" (
  echo [ERROR] Blender was not found at:
  echo %BLENDER_EXECUTABLE%
  echo Edit BLENDER_EXECUTABLE in run_blender_agent.bat and this script.
  pause
  exit /b 1
)

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  if not exist "%LOCALAPPDATA%\BlenderWorkAgent" mkdir "%LOCALAPPDATA%\BlenderWorkAgent"
  py -3.11 -m venv "%AGENT_VENV%"
  if errorlevel 1 goto failed
)

echo.
echo This Blender launcher uses Python standard-library modules only.
echo No pip packages or API credentials are required.
echo.
echo Setup completed. No credentials are needed.
echo Installing automatic startup for the current Windows user...
if exist "%~dp0install_blender_agent_autostart.ps1" (
  set "BLENDER_AGENT_AUTOSTART_SILENT=1"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_blender_agent_autostart.ps1"
  if errorlevel 1 (
    echo [WARNING] Agent setup succeeded, but automatic startup could not be installed.
    echo Run install_blender_agent_autostart.bat manually later.
  ) else (
    echo Automatic startup installed. The agent console will open when you sign in.
  )
) else (
  echo [WARNING] Autostart installer was not found in this folder.
)
echo.
echo Next: launch run_blender_agent.bat now, or sign out and sign in to test autostart.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] Setup failed. Existing files were not deleted.
pause
exit /b 1
