# One-time bootstrap for the pinned Episode 1 asset-sync update.
# This is intentionally run locally once; the existing updater excludes itself
# and cannot add new trusted paths through a normal update.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Repo = 'bjiow131/free-video-generator'
$Commit = 'ee18d7e24a0eee67db7d8d9edef49ccfbb0b3dfa'
$Target = 'C:\AI-Agent-Studio-Octava'
$Python = Join-Path $env:LOCALAPPDATA 'BlenderWorkAgent\github-venv\Scripts\python.exe'
$Files = @(
  @{ Path = 'docs/local-agent/asset-sync.md'; Blob = 'cf28f738651bb82c1c79b930dda37f71b64d4732' },
  @{ Path = 'docs/season1/asset_sync_manifest.json'; Blob = '547166cf72d1bfc72ec420c975d7a0f3358412e6' },
  @{ Path = 'local_agent/blender_rigging.py'; Blob = '3cc29237d2ad5f2412ccdd93bfe3a186d87a6172' },
  @{ Path = 'local_agent/blender_workflow.py'; Blob = '60c758730ed25897267865496f19a83c864dbd5e' },
  @{ Path = 'local_agent/control_protocol.py'; Blob = 'bcc971d296b3edad4a82c982c827cd620a03c538' },
  @{ Path = 'local_agent/github_asset_sync.py'; Blob = '46502d433b8578ca10241eb76b119be6641824d2' },
  @{ Path = 'local_agent/mailbox_policy.py'; Blob = '03f72c27a9784ae77453def03e4ced08711f7de9' },
  @{ Path = 'local_agent/poller.py'; Blob = '5a53a33814363f623297438233ccd11444d1c429' },
  @{ Path = 'local_agent/studio_static/app.js'; Blob = '699831111baa5968b73e5aafff42e44b7406cff8' },
  @{ Path = 'local_agent/trusted_updates.py'; Blob = 'bb0b8932487cc1a9032e13786ba87cb0cb4cf570' },
  @{ Path = 'tests/test_asset_sync_protocol.py'; Blob = 'dac894a15cb581e4554bbe40832c6d508b8140fe' },
  @{ Path = 'tests/test_github_asset_sync.py'; Blob = 'd4688ab7a405134fb5e6b4dc7b4466b0ff4ae27b' },
  @{ Path = 'tests/test_github_asset_sync_resume.py'; Blob = 'ea327cdb4a5ee85145da8bdb0c42e01d19b7bb10' },
  @{ Path = 'tests/test_mailbox_policy.py'; Blob = 'bd4391ee88392f60391b2ec05cc4d4018c26a3c8' },
  @{ Path = 'tests/test_trusted_updates.py'; Blob = 'f28c2764a493378d3c26ec2fd681f48e34e1a76b' }
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
    $url = "https://api.github.com/repos/$Repo/contents/$encodedPath" + '?ref=' + $Commit
    $response = Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 30 -Headers @{
      Accept = 'application/vnd.github+json'
      'X-GitHub-Api-Version' = '2022-11-28'
      'User-Agent' = 'blender-agent-local-bootstrap'
    }
    if ($response.type -ne 'file' -or $response.path -ne $File.Path -or
        $response.encoding -ne 'base64' -or $response.sha -ne $File.Blob) {
      throw "Pinned GitHub metadata mismatch: $($File.Path)"
    }
    $bytes = [Convert]::FromBase64String(($response.content -replace '\s',''))
    if ($bytes.Length -lt 1 -or $bytes.Length -gt 500000 -or
        $response.size -ne $bytes.Length -or (Get-GitBlobSha1 $bytes) -ne $File.Blob) {
      throw "Pinned file verification failed: $($File.Path)"
    }
    $stagePath = Join-Path $Stage ($File.Path.Replace('/', '\'))
    New-Item -ItemType Directory -Path (Split-Path -Parent $stagePath) -Force | Out-Null
    [IO.File]::WriteAllBytes($stagePath, $bytes)
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
      [IO.File]::Replace($stagePath, $destination, $null)
    } else {
      [IO.File]::Move($stagePath, $destination)
    }
  }
  $Installed = $true

  Push-Location $Target
  try {
    & $Python -m pytest -q tests/test_trusted_updates.py tests/test_unattended_poller.py tests/test_asset_sync_protocol.py tests/test_github_asset_sync.py tests/test_github_asset_sync_resume.py tests/test_mailbox_policy.py
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
