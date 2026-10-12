# Windows PowerShell 5.1: exercise the exact replacement primitive from local V4 installer.
$ErrorActionPreference = 'Stop'
function Assert($condition, [string]$message) {
    if (-not $condition) { throw $message }
}
function AtomicCopy([string]$source, [string]$destination) {
    # Windows PowerShell 5.1 (.NET Framework) requires a real, fully-qualified
    # backup path for File.Replace. Passing $null can throw ArgumentException.
    $srcFull = [System.IO.Path]::GetFullPath($source)
    $dstFull = [System.IO.Path]::GetFullPath($destination)
    Assert ([System.IO.File]::Exists($srcFull)) "Missing update source: $srcFull"
    Assert ([System.IO.File]::Exists($dstFull)) "Missing existing target: $dstFull"
    $dir = [System.IO.Path]::GetDirectoryName($dstFull)
    $nonce = [guid]::NewGuid().ToString('N')
    $temp = [System.IO.Path]::Combine($dir, ".octava-stage-$nonce.tmp")
    $previous = [System.IO.Path]::Combine($dir, ".octava-previous-$nonce.bak")
    $swapped = $false
    try {
        [System.IO.File]::Copy($srcFull, $temp, $false)
        [System.IO.File]::Replace($temp, $dstFull, $previous)
        $swapped = $true
    } finally {
        if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) }
        # Only remove the short-lived previous-version file after successful
        # replacement; the full persistent backups live under $backup/files.
        # On failure retain it for manual recovery.
        if ($swapped -and [System.IO.File]::Exists($previous)) {
            [System.IO.File]::Delete($previous)
        }
    }
}
$dir = Join-Path $env:TEMP ("octava-v4-canary-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $dir | Out-Null
    $from = Join-Path $dir 'from.txt'
    $to = Join-Path $dir 'to.txt'
    [System.IO.File]::WriteAllText($from, "AFTER")
    [System.IO.File]::WriteAllText($to, "BEFORE")
    AtomicCopy $from $to
    Assert ([System.IO.File]::ReadAllText($to) -eq "AFTER") 'V4 file replace content mismatch'
    Assert ([System.IO.File]::Exists($from)) 'Source download must be preserved for retries and rollback'
    Assert (@(Get-ChildItem $dir -Filter ".octava-*").Count -eq 0) 'Temp files not cleaned'
    Write-Host "V4 Windows atomic file replacement: PASS"
} finally {
    if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
}
