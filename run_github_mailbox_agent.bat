@echo off
setlocal
cd /d "%~dp0"

rem Explicit opt-in: the regular local Blender launcher never polls GitHub.
set "LOCAL_AGENT_ENABLE_GITHUB_MAILBOX=1"
if not defined LOCAL_AGENT_GITHUB_REPO set "LOCAL_AGENT_GITHUB_REPO=bjiow131/local-agent-mailbox"
if not defined LOCAL_AGENT_GITHUB_REF set "LOCAL_AGENT_GITHUB_REF=main"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m local_agent.poller
) else (
    python -m local_agent.poller
)
set "AGENT_EXIT=%ERRORLEVEL%"
if not "%AGENT_EXIT%"=="0" (
    echo GitHub mailbox agent exited with code %AGENT_EXIT%.
    echo Check docs\github-mailbox-windows.md and local credentials.
    pause
)
exit /b %AGENT_EXIT%
