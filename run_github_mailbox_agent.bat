@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "LOCAL_AGENT_GITHUB_BACKUP_REPO=bjiow131/octava-agent-backup-mailbox"
set "LOCAL_AGENT_GITHUB_BACKUP_REF=main"
set "LOCAL_AGENT_GITHUB_BACKUP_MANIFEST=queue/desired_task.json"
rem Owner authorized computer operations through both private mailboxes on 2026-10-15.
set "LOCAL_AGENT_ALLOW_COMPUTER_CONTROL=1"
set "PYTHONUNBUFFERED=1"
title Blender Octava - Studio and GitHub Agent Supervisor

set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\github-venv"
set "LOCAL_AGENT_ENABLE_GITHUB_MAILBOX=1"
if not defined LOCAL_AGENT_ALLOW_REMOTE_RESTART set "LOCAL_AGENT_ALLOW_REMOTE_RESTART=1"
if not defined LOCAL_AGENT_WORKSPACE set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"
if not defined LOCAL_AGENT_GITHUB_REPO set "LOCAL_AGENT_GITHUB_REPO=bjiow131/local-agent-mailbox"
if not defined LOCAL_AGENT_GITHUB_REF set "LOCAL_AGENT_GITHUB_REF=main"

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  echo [ERROR] GitHub agent virtual environment not installed.
  echo Run setup_github_mailbox_agent.bat once.
  exit /b 1
)

if /I "%~1"=="--recover-services" (
  "%AGENT_VENV%\Scripts\python.exe" -m local_agent.poller --recover-services
  exit /b
)

echo Starting supervised Blender Studio and GitHub agent.
echo Background Blender rendering; Studio URL http://127.0.0.1:55313/
echo Recovery checks every 2 seconds. Windows login autostart enabled.
echo Remote restart accepts only an empty, fixed request and waits for active renders.
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.poller --supervise
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo [WARNING] Supervisor ended with code %RESULT%.
endlocal & exit /b %RESULT%

