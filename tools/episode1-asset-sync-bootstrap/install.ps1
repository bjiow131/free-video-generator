# One-time bootstrap for the pinned Episode 1 asset-sync update.
# This is intentionally run locally once; the existing updater excludes itself
# and cannot add new trusted paths through a normal update.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bjiow131/free-video-generator'
$Commit = '05037b3034a60e873669f253c273de4eae047795'
$Target = 'C:\AI-Agent-Studio-Octava'
$Python = Join-Path $env:LOCALAPPDATA 'BlenderWorkAgent\github-venv\Scripts\python.exe'
$Files = @(
  @{ Path = 'local_agent/trusted_updates.py'; Blob = 'c76ae9b46fc6cdb968a8932cecbe3ed0431ebcd5' },
  @{ Path = 'local_agent/dropbox_review.py'; Blob = '7fc21f75b05d1624c4a71026c9b99536d2c78662' },
  @{ Path = 'tests/test_trusted_updates.py'; Blob = 'b8795ee69fc1378bfc0e1bd8ef6e6558407d852e' }
)

function Assert-NotReparsePoint([string] $Path) {
  if (Test-Path -LiteralPath $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "Refusing linked path: $Path"
    }
  }
}

function Get-GitBlobSha1([byte[]] $Bytes) {
  $header = [Text.Encoding]::ASCII.GetBytes(('blob ' + $Bytes.Length + [char]0))
  $combined = New-Object byte[] ($header.Length + $Bytes.Length)
  [Array]::Copy($header, 0, $combined, 0, $header.Length)
  [Array]::Copy($Bytes, 0, $combined, $header.Length, $Bytes.Length)
  $sha = [Security.Cryptography.SHA1]::Create()
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($combined))).Replace('-', '').ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

$Target = [IO.Path]::GetFullPath($Target)
if ($Target -ne 'C:\AI-Agent-Studio-Octava') { throw 'Unexpected fixed installation path' }
Assert-NotReparsePoint $Target
if (!(Test-Path -LiteralPath (Join-Path $Target 'local_agent\poller.py') -PathType Leaf)) {
  throw "Existing Blender Agent not found at $Target"
}
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw 'Agent Python environment not found; installation aborted.'
}
if ((Get-Item -LiteralPath $Target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
  throw 'Installation directory must not be a junction or symlink.'
}

$StateRoot = Join-Path $Target '.local_agent\trusted_update_bootstrap'
Assert-NotReparsePoint (Join-Path $Target '.local_agent')
Assert-NotReparsePoint $StateRoot
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
$Id = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$Stage = Join-Path $StateRoot ($Id + '-stage')
$Backup = Join-Path $StateRoot ($Id + '-backup')
New-Item -ItemType Directory -Path $Stage,$Backup -Force | Out-Null
$Touched = New-Object System.Collections.Generic.List[object]
$Installed = $false

try {
  # Fetch and verify every byte before touching the installation.
  foreach ($File in $Files) {
    if ($File.Path -notmatch '^[A-Za-z0-9_./-]+$' -or $File.Path.Contains('..')) {
      throw 'Unsafe pinned file path.'
    }
    $encodedPath = (($File.Path -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
    $stagePath = Join-Path $Stage ($File.Path.Replace('/', '\'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $stagePath) -Force | Out-Null
    $url = "https://raw.githubusercontent.com/$Repo/$Commit/$encodedPath"
    Invoke-WebRequest -Method Get -Uri $url -TimeoutSec 30 -Headers @{
      'User-Agent' = 'blender-agent-local-bootstrap'
    } -OutFile $stagePath -UseBasicParsing
    $bytes = [IO.File]::ReadAllBytes($stagePath)
    if ($bytes.Length -lt 1 -or $bytes.Length -gt 500000 -or
        (Get-GitBlobSha1 $bytes) -ne $File.Blob) {
      throw "Pinned file verification failed: $($File.Path)"
    }
  }

  # Back up existing regular files and reject links before installing.
  foreach ($File in $Files) {
    $relative = $File.Path.Replace('/', '\')
    $destination = Join-Path $Target $relative
    $parent = Split-Path -Parent $destination
    while ($parent.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase)) {
      Assert-NotReparsePoint $parent
      if ($parent -eq $Target) { break }
      $parent = Split-Path -Parent $parent
    }
    Assert-NotReparsePoint $destination
    $exists = Test-Path -LiteralPath $destination
    if ($exists -and !(Test-Path -LiteralPath $destination -PathType Leaf)) {
      throw "Destination is not a regular file: $($File.Path)"
    }
    $backupPath = Join-Path $Backup $relative
    if ($exists) {
      New-Item -ItemType Directory -Path (Split-Path -Parent $backupPath) -Force | Out-Null
      Copy-Item -LiteralPath $destination -Destination $backupPath
    }
    $Touched.Add(@{ Path = $destination; Backup = $backupPath; Existed = $exists; Relative = $relative })
  }

  foreach ($Item in $Touched) {
    $destination = $Item.Path
    $stagePath = Join-Path $Stage $Item.Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    if ($Item.Existed) {
      # Windows PowerShell/.NET Framework requires a valid backup path here;
      # passing $null raises "The path is not of a legal form".
      $replaceBackup = $destination + '.' + $Id + '.replace-backup'
      [IO.File]::Replace($stagePath, $destination, $replaceBackup)
      Remove-Item -LiteralPath $replaceBackup -Force
    } else {
      [IO.File]::Move($stagePath, $destination)
    }
  }
  $Installed = $true

  Push-Location $Target
  try {
    & $Python -m pytest -q tests/test_unattended_poller.py tests/test_asset_sync_protocol.py tests/test_github_asset_sync.py tests/test_github_asset_sync_resume.py tests/test_mailbox_policy.py tests/test_trusted_updates.py::test_episode_asset_sync_paths_are_allowlisted_without_allowing_updater_self_update tests/test_trusted_updates.py::test_pinned_update_fetch_uses_rate_limit_free_raw_content tests/test_trusted_updates.py::test_episode1_export_accepts_only_gzip_wrapped_blender_headers
    if ($LASTEXITCODE -ne 0) { throw "Focused Windows tests failed: exit=$LASTEXITCODE" }
  } finally {
    Pop-Location
  }

  Write-Host "Bootstrap completed from pinned commit $Commit."
  Write-Host "Backup retained at $Backup"
  Write-Host 'The new asset-sync permission remains disabled until enabled in Studio.'
  Write-Host 'Restart the GitHub mailbox agent and Studio after installation.'
} catch {
  Write-Host ("Bootstrap failed: " + $_.Exception.Message) -ForegroundColor Red
  if ($Touched.Count -gt 0) {
    foreach ($Item in ($Touched | Select-Object -Last $Touched.Count)) {
      try {
        if ($Item.Existed -and (Test-Path -LiteralPath $Item.Backup -PathType Leaf)) {
          Copy-Item -LiteralPath $Item.Backup -Destination $Item.Path -Force
        } elseif (!$Item.Existed) {
          Remove-Item -LiteralPath $Item.Path -Force -ErrorAction SilentlyContinue
        }
      } catch {
        Write-Host ("Rollback failed for " + $Item.Relative + "; backup retained.") -ForegroundColor Yellow
      }
    }
  }
  throw
} finally {
  if (Test-Path -LiteralPath $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
  }
}
