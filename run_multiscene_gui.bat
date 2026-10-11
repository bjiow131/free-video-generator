@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "AGENT_PY=%LOCALAPPDATA%\BlenderWorkAgent\venv\Scripts\python.exe"
if not exist "%AGENT_PY%" (
  echo Agent environment not found. Run setup_blender_agent.bat first.
  pause
  exit /b 1
)
"%AGENT_PY%" -m local_agent.multiscene_gui
if errorlevel 1 pause
