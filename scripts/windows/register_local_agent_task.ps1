[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "This script is for Windows 10/11 only." }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runner = Join-Path $PSScriptRoot "run_local_agent.ps1"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) { throw "Run setup_local_agent.ps1 before registering the background task." }
$TaskName = "AIStudio Local Agent"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $Runner + '"'
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Starts the local-first AI Studio agent after this Windows user signs in." -Force | Out-Null
Write-Host "Registered '$TaskName'. It starts at the next Windows sign-in and writes logs to .local_agent\logs\poller.log."
Write-Warning "This does not auto-sign in after a reboot. A Windows user must sign in once after restart; automatic sign-in is intentionally not enabled."
Write-Host "Start it now with: Start-ScheduledTask -TaskName '$TaskName'"
