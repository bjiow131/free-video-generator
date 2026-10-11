[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $RepoRoot ".local_agent\logs"
$LogPath = Join-Path $LogDir "poller.log"
if (-not (Test-Path $Python -PathType Leaf)) { throw "Local agent virtual environment is missing. Run setup_local_agent.ps1 first." }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ((Test-Path $LogPath -PathType Leaf) -and (Get-Item $LogPath).Length -gt 2MB) {
    Move-Item -Force $LogPath "$LogPath.1"
}
Set-Location $RepoRoot
"[$(Get-Date -Format o)] Starting local agent poller" | Out-File -FilePath $LogPath -Append -Encoding utf8
$env:LOCAL_AGENT_ENABLE_GITHUB_MAILBOX = "1"
$env:PYTHONUTF8 = "1"
Write-Host "Each task needs approval in this console; unattended execution is unavailable."
# Keep approval prompts visible. Individual task reports remain on disk.
& $Python -u -m local_agent.poller
$ExitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] Poller exited with code $ExitCode" | Out-File -FilePath $LogPath -Append -Encoding utf8
exit $ExitCode
