@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Blender Work Agent
set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\venv"
set "BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"
set "LOCAL_AGENT_GITHUB_REPO=bjiow131/local-agent-mailbox"
set "LOCAL_AGENT_GITHUB_REF=main"
set "LOCAL_AGENT_GITHUB_MANIFEST=queue/desired_task.json"
set "LOCAL_AGENT_POLL_SECONDS=10"

echo.
echo ==========================================
echo   BLENDER WORK AGENT
echo ==========================================
echo.
echo Blender: %BLENDER_EXECUTABLE%
echo Workspace: %LOCAL_AGENT_WORKSPACE%
echo Mailbox: %LOCAL_AGENT_GITHUB_REPO%
echo.
echo This agent does not launch the web application.
echo Each task must be approved in this local console.
echo Press Ctrl+C to stop polling.
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

"%AGENT_VENV%\Scripts\python.exe" -m local_agent.poller
set "RESULT=%ERRORLEVEL%"
echo.
echo Blender Work Agent stopped with code %RESULT%.
pause
exit /b %RESULT%
