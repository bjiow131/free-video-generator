@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\github-venv"

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python Launcher was not found. Install Python 3.11 and rerun.
  pause
  exit /b 1
)

py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.11 is required.
  pause
  exit /b 1
)

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  if not exist "%LOCALAPPDATA%\BlenderWorkAgent" mkdir "%LOCALAPPDATA%\BlenderWorkAgent"
  py -3.11 -m venv "%AGENT_VENV%"
  if errorlevel 1 goto failed
)

echo Installing GitHub mailbox transport and isolated repair-test dependencies...
"%AGENT_VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements-github-mailbox.txt"
if errorlevel 1 goto failed

echo.
echo GitHub mailbox environment is ready.
echo Next: store a fine-grained token with:
echo "%AGENT_VENV%\Scripts\python.exe" -m local_agent.credentials_cli set
echo Then run scripts\check_github_connection.py and run_github_mailbox_agent.bat.
pause
exit /b 0

:failed
echo.
echo [ERROR] GitHub mailbox setup failed. The local-only Blender environment was not changed.
pause
exit /b 1
