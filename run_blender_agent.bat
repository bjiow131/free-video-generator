@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Blender Work Agent - Local Only
set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\venv"
set "BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"

echo.
echo ==========================================================
echo   BLENDER WORK AGENT - LOCAL ONLY
echo ==========================================================
echo.
echo Blender: %BLENDER_EXECUTABLE%
echo Workspace: %LOCAL_AGENT_WORKSPACE%
echo Remote task queue: DISABLED
echo ChatGPT connection: NONE
echo Browser / other-app control: NONE
echo.
echo The menu offers only allowlisted Blender operations.
echo Each operation that changes files asks for confirmation.
echo.

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  echo [ERROR] Agent environment is missing.
  echo Run setup_blender_agent.bat first.
  pause
  exit /b 1
)

if not exist "%BLENDER_EXECUTABLE%" (
  echo [ERROR] Blender was not found at:
  echo %BLENDER_EXECUTABLE%
  echo Edit BLENDER_EXECUTABLE in run_blender_agent.bat.
  pause
  exit /b 1
)

if not exist "%LOCAL_AGENT_WORKSPACE%" mkdir "%LOCAL_AGENT_WORKSPACE%"
if not exist "%LOCAL_AGENT_WORKSPACE%" (
  echo [ERROR] Could not create the workspace.
  pause
  exit /b 1
)

echo [1/2] Checking local prerequisites...
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.cli preflight
if errorlevel 1 (
  echo [ERROR] Preflight failed. Read the report above before continuing.
  pause
  exit /b 1
)

echo.
echo [2/2] Starting the local Blender workbench...
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.workbench_cli
set "RESULT=%ERRORLEVEL%"
echo.
echo Blender Work Agent ended with code %RESULT%.
pause
exit /b %RESULT%
