param(
  [string]$Target = 'C:\AI-Agent',
  [Parameter(Mandatory=$true)][string]$Backup
)
$ErrorActionPreference = 'Stop'
$targetRoot = [IO.Path]::GetFullPath($Target)
$backupRoot = [IO.Path]::GetFullPath($Backup)
if (-not (Test-Path (Join-Path $backupRoot 'new-files.txt') -PathType Leaf)) {
    throw 'Нет манифеста резервной копии. Откат остановлен.'
}
if (-not $backupRoot.StartsWith(($targetRoot.TrimEnd('\') + '\backup-studio-'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backup должен находиться в папке backup-studio-* внутри указанного Target.'
}
foreach ($line in Get-Content (Join-Path $backupRoot 'new-files.txt') -Encoding UTF8) {
    if ($line -notmatch '^(?:local_agent|tests|docs)\\[A-Za-z0-9_.\\-]+$|^[A-Za-z0-9_.-]+$') {
        throw "Недопустимый путь: $line"
    }
    $dest = Join-Path $targetRoot $line
    if (Test-Path $dest -PathType Leaf) { Remove-Item $dest -Force }
}
Get-ChildItem -LiteralPath $backupRoot -Recurse -File | Where-Object { $_.Name -ne 'new-files.txt' } | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($backupRoot, $_.FullName)
    $destination = Join-Path $targetRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item $_.FullName $destination -Force
}
Write-Host "Studio rollback complete from $backupRoot"
