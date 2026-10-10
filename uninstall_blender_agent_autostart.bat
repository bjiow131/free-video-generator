@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\Blender Work Agent.lnk"
if exist "%SHORTCUT%" (
  del "%SHORTCUT%"
  if errorlevel 1 (
    echo [ERROR] Could not remove the startup shortcut.
    pause
    exit /b 1
  )
  echo Blender Work Agent autostart has been removed.
) else (
  echo No Blender Work Agent autostart shortcut was found.
)
echo Existing projects and Blender files were not changed.
pause
