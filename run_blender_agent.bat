@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"

title Blender Work Agent - Local Only
set "AGENT_VENV=%LOCALAPPDATA%\BlenderWorkAgent\venv"
if not defined LOCAL_AGENT_WORKSPACE set "LOCAL_AGENT_WORKSPACE=C:\AI-Agent-Workspace"

echo.
echo ==========================================
echo   BLENDER WORK AGENT - LOCAL ONLY
echo ==========================================
echo.
echo Blender executable: auto-detect installed Blender or BLENDER_EXECUTABLE override
echo Workspace: %LOCAL_AGENT_WORKSPACE%
echo Remote task queue: DISABLED
echo ChatGPT connection: NONE
echo.
echo This agent is limited to the local Blender bridge.
echo The current prototype task is a deterministic forest preview.
echo.

if not exist "%AGENT_VENV%\Scripts\python.exe" (
  echo [ERROR] Agent environment is missing.
  echo Run setup_blender_agent.bat first.
  pause
  exit /b 1
)

if not exist "%LOCAL_AGENT_WORKSPACE%" mkdir "%LOCAL_AGENT_WORKSPACE%"
if not exist "%LOCAL_AGENT_WORKSPACE%" (
  echo [ERROR] Could not create the workspace.
  pause
  exit /b 1
)

echo [1/2] Checking local prerequisites...
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.cli preflight
if errorlevel 1 (
  echo [ERROR] Preflight failed. Read the report above before continuing.
  pause
  exit /b 1
)

echo.
echo [2/2] Blender will open in its visible GUI for the task.
choice /C YN /N /M "Create the current Blender forest preview now? [Y/N] "
if errorlevel 2 goto done

rem Keep typed data in the environment; never interpolate it into cmd.exe source.
set "LOCAL_AGENT_PROJECT_NAME=mia_forest"
set /p "LOCAL_AGENT_PROJECT_NAME=Project folder name (default mia_forest): "

echo.
echo Launching Blender locally...
"%AGENT_VENV%\Scripts\python.exe" -m local_agent.blender_cli
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
  echo Blender task completed. Check the project folder inside your configured workspace.
) else (
  echo Blender task returned error code %RESULT%.
)
goto finish

:done
echo No Blender scene was created. Preflight only.
set "RESULT=0"

:finish
echo.
echo Agent session ended with code %RESULT%.
pause
exit /b %RESULT%
