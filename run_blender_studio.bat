@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Blender Octava Studio
if not defined LOCAL_AGENT_STUDIO_PORT set "LOCAL_AGENT_STUDIO_PORT=55313"
rem There is one owner of Studio and mailbox; do not launch a duplicate server.
rem The per-user supervisor will start or recover both services automatically.
start "" "%~dp0run_github_mailbox_agent.bat"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%LOCAL_AGENT_STUDIO_PORT%/"
endlocal
