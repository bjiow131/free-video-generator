@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\github-venv"
set "LOCAL_AGENT_ENABLE_GITHUB_MAILBOX=1"
if not defined LOCAL_AGENT_WORKSPACE set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"
if not exist "%LOCAL_AGENT_WORKSPACE%" mkdir "%LOCAL_AGENT_WORKSPACE%" 2>nul
if not defined LOCAL_AGENT_GITHUB_REPO set "LOCAL_AGENT_GITHUB_REPO=bjiow131/local-agent-mailbox"
if not defined LOCAL_AGENT_GITHUB_REF set "LOCAL_AGENT_GITHUB_REF=main"

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  echo [ERROR] GitHub mailbox environment is missing.
  echo Run setup_github_mailbox_agent.bat first.
  pause
  exit /b 1
)

echo Starting opt-in GitHub mailbox agent.
echo Repository: %LOCAL_AGENT_GITHUB_REPO%
echo Branch: %LOCAL_AGENT_GITHUB_REF%
echo Task confirmations depend on the locally saved Studio policy.
echo Unattended operations run without YES only after enabling the checkbox in Studio Settings.
:run_loop
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.poller
set "AGENT_EXIT=%ERRORLEVEL%"
if "%AGENT_EXIT%"=="75" (
  echo Trusted update was applied. Restarting agent with updated code...
  timeout /t 2 /nobreak >nul
  goto run_loop
)
if not "%AGENT_EXIT%"=="0" (
  echo GitHub mailbox agent exited with code %AGENT_EXIT%.
  pause
)
exit /b %AGENT_EXIT%
