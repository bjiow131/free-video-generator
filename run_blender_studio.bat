@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined LOCAL_AGENT_WORKSPACE set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"
rem Studio imports the trusted update preferences, whose updater depends on
rem requests. Use the isolated GitHub Python environment if it is installed.
rem The Studio server remains local-only and does not require internet to run.
set "AGENT_PY=%LOCALAPPDATA%\BlenderWorkAgent\github-venv\Scripts\python.exe"
if exist "%AGENT_PY%" goto run
set "AGENT_PY=%LOCALAPPDATA%\BlenderWorkAgent\venv\Scripts\python.exe"
if exist "%AGENT_PY%" goto run
where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.11 or local agent virtual environment not found.
  echo Run setup_blender_agent.bat first.
  pause
  exit /b 1
)
set "AGENT_PY=py -3.11"
:run
echo Blender AI Agent Studio - local only
echo Workspace: %LOCAL_AGENT_WORKSPACE%
echo The browser will open automatically. Keep this terminal running.
%AGENT_PY% -m local_agent.studio_server --workspace "%LOCAL_AGENT_WORKSPACE%" --project mia_story
if errorlevel 1 (
  echo [ERROR] Studio failed. Copy the error displayed above.
  pause
)
endlocal
