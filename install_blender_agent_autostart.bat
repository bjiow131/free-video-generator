@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Windows PowerShell was not found.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_blender_agent_autostart.ps1"
if errorlevel 1 (
  echo [ERROR] Could not install autostart.
  pause
  exit /b 1
)
