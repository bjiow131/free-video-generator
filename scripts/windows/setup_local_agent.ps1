[CmdletBinding()]
param(
    [string]$Workspace = (Join-Path $HOME "AIStudioWorkspace"),
    [switch]$SkipCredentialPrompt
)
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host "WARNING: $Message" -ForegroundColor Yellow }

if ($env:OS -ne "Windows_NT") { throw "This setup script is for Windows 10/11 only." }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Requirements = Join-Path $RepoRoot "requirements-local-agent.txt"
if (-not (Test-Path $Requirements -PathType Leaf)) { throw "Missing requirements-local-agent.txt. Run this from the agent source checkout." }

Write-Step "Check Python"
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$PythonCommand = $null
if ($PythonLauncher) {
    try {
        & py -3.11 --version | Out-Null
        if ($LASTEXITCODE -eq 0) { $PythonCommand = "py -3.11" }
    } catch {}
}
if (-not $PythonCommand) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        $VersionText = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
        $Parts = $VersionText.Trim().Split(".")
        if ($Parts.Count -ge 2 -and [int]$Parts[0] -eq 3 -and [int]$Parts[1] -ge 11) { $PythonCommand = "python" }
    }
}
if (-not $PythonCommand) {
    throw "Python 3.11+ was not found. Install Python 3.11 or 3.12, enable the Python Launcher, then rerun this script."
}
Write-Host "Selected interpreter command: $PythonCommand"

Write-Step "Create isolated virtual environment"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    if ($PythonCommand -eq "py -3.11") { & py -3.11 -m venv (Join-Path $RepoRoot ".venv") }
    else { & python -m venv (Join-Path $RepoRoot ".venv") }
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
}
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) { throw "Local agent dependency installation failed." }

Write-Step "Create private local workspace"
$Workspace = [System.IO.Path]::GetFullPath($Workspace)
New-Item -ItemType Directory -Force -Path $Workspace, (Join-Path $Workspace "projects"), (Join-Path $Workspace "reports"), (Join-Path $Workspace "logs") | Out-Null
[Environment]::SetEnvironmentVariable("LOCAL_AGENT_WORKSPACE", $Workspace, "User")
$env:LOCAL_AGENT_WORKSPACE = $Workspace
Write-Host "Workspace: $Workspace"

Write-Step "Configure non-secret mailbox settings"
$CurrentRepo = [Environment]::GetEnvironmentVariable("LOCAL_AGENT_GITHUB_REPO", "User")
if (-not $CurrentRepo) {
    $EnteredRepo = Read-Host "Private GitHub mailbox repository (owner/repo; not the public source repository)"
    if ($EnteredRepo -match "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$") {
        [Environment]::SetEnvironmentVariable("LOCAL_AGENT_GITHUB_REPO", $EnteredRepo, "User")
        $env:LOCAL_AGENT_GITHUB_REPO = $EnteredRepo
    } else {
        Write-Warn "Mailbox repository was not configured. Set LOCAL_AGENT_GITHUB_REPO later."
    }
}
$CurrentRef = [Environment]::GetEnvironmentVariable("LOCAL_AGENT_GITHUB_REF", "User")
if (-not $CurrentRef) {
    [Environment]::SetEnvironmentVariable("LOCAL_AGENT_GITHUB_REF", "main", "User")
    $env:LOCAL_AGENT_GITHUB_REF = "main"
}
$CurrentManifest = [Environment]::GetEnvironmentVariable("LOCAL_AGENT_GITHUB_MANIFEST", "User")
if (-not $CurrentManifest) {
    [Environment]::SetEnvironmentVariable("LOCAL_AGENT_GITHUB_MANIFEST", "queue/desired_task.json", "User")
    $env:LOCAL_AGENT_GITHUB_MANIFEST = "queue/desired_task.json"
}
$CurrentPoll = [Environment]::GetEnvironmentVariable("LOCAL_AGENT_POLL_SECONDS", "User")
if (-not $CurrentPoll) {
    [Environment]::SetEnvironmentVariable("LOCAL_AGENT_POLL_SECONDS", "10", "User")
    $env:LOCAL_AGENT_POLL_SECONDS = "10"
}

Write-Step "Detect optional tools"
$Git = Get-Command git -ErrorAction SilentlyContinue
if ($Git) { & git --version } else { Write-Warn "Git is not installed or not on PATH. Diagnostics still work; reviewed git patches will be blocked." }
$Blender = Get-Command blender -ErrorAction SilentlyContinue
if ($Blender) {
    [Environment]::SetEnvironmentVariable("BLENDER_EXECUTABLE", $Blender.Source, "User")
    $env:BLENDER_EXECUTABLE = $Blender.Source
    Write-Host "Blender: $($Blender.Source)"
} elseif (-not [Environment]::GetEnvironmentVariable("BLENDER_EXECUTABLE", "User")) {
    Write-Warn "Blender was not detected. Install Blender or set BLENDER_EXECUTABLE later; setup does not download or install it."
}
$Gpu = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($Gpu) { & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader } else { Write-Warn "nvidia-smi unavailable. The agent can still run CPU diagnostics; GPU rendering is not yet verified." }

Write-Step "Run safe local diagnostics"
& $VenvPython -m local_agent.cli doctor
if ($LASTEXITCODE -ne 0) { Write-Warn "Diagnostics returned a non-zero exit code." }

Write-Step "Run focused agent tests"
& $VenvPython -m pytest -q tests/test_control_protocol.py tests/test_poller.py tests/test_github_queue.py tests/test_story_plan.py tests/test_scene_compiler.py tests/test_asset_registry.py tests/test_preflight.py
if ($LASTEXITCODE -ne 0) { Write-Warn "Some focused tests failed. Do not start mailbox polling until reviewed." }

if (-not $SkipCredentialPrompt) {
    Write-Step "Configure GitHub token in Windows Credential Manager"
    Write-Host "Create a fine-grained token for the PRIVATE mailbox repository only, with Contents read/write."
    Write-Host "Do not paste the token into chat, a script, a task manifest, or a .env file."
    $DoToken = Read-Host "Store or check the token now? (set/status/skip)"
    if ($DoToken -in @("set", "status", "delete")) {
        & $VenvPython -m local_agent.credentials_cli $DoToken
    } else {
        Write-Warn "Token setup skipped. The poller will not connect until a token is stored."
    }
}

Write-Step "Run local-only preflight"
& $VenvPython -m local_agent.cli preflight
if ($LASTEXITCODE -ne 0) { Write-Warn "Preflight reports missing setup. Review the checks before starting the poller." }

Write-Step "Setup summary"
Write-Host "Source: $RepoRoot"
Write-Host "Workspace: $Workspace"
Write-Host "Next: review docs/local-agent/windows-first-run-and-failure-matrix.md"
Write-Host "Do not start the poller until the mailbox repository is PRIVATE, its manifest is valid, and focused tests pass."
Write-Host "Start manually with: .\.venv\Scripts\python.exe -m local_agent.poller"
