@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"
title Blender Work Agent
set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\venv"
if not defined BLENDER_EXECUTABLE (
  for /f "delims=" %%B in ('where blender.exe 2^>nul') do if not defined BLENDER_EXECUTABLE set "BLENDER_EXECUTABLE=%%B"
)
if not defined BLENDER_EXECUTABLE (
  for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender *") do (
    if exist "%%~fD\blender.exe" set "BLENDER_EXECUTABLE=%%~fD\blender.exe"
  )
)
set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"
set "LOCAL_AGENT_CHARACTER_LIBRARY=%USERPROFILE%\BlenderAgentLibrary"

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  echo [ERROR] Agent environment is missing.
  echo Run setup_blender_agent.bat first.
  pause
  exit /b 1
)
if not exist "%BLENDER_EXECUTABLE%" (
  echo [ERROR] Blender was not found at:
  echo %BLENDER_EXECUTABLE%
  echo Set BLENDER_EXECUTABLE to the full path of blender.exe and retry.
  pause
  exit /b 1
)
if not exist "%LOCAL_AGENT_WORKSPACE%" mkdir "%LOCAL_AGENT_WORKSPACE%"
if not exist "%LOCAL_AGENT_CHARACTER_LIBRARY%" mkdir "%LOCAL_AGENT_CHARACTER_LIBRARY%"
if not exist "%LOCAL_AGENT_WORKSPACE%" (
  echo [ERROR] Could not create the workspace.
  pause
  exit /b 1
)
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.cli preflight
if errorlevel 1 (
  echo [ERROR] Preflight failed. Read the report above before continuing.
  pause
  exit /b 1
)
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.app_gui
if errorlevel 1 (
  echo [ERROR] Could not launch the GUI.
  pause
  exit /b 1
)
exit /b 0
