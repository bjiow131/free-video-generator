param([string]$Target = 'C:\AI-Agent')
$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
if (!(Test-Path (Join-Path $Target 'local_agent\multiscene_cli.py'))) {
    throw "Существующая Blender AI Agent программа не найдена в $Target"
}
$Names = @(
    'local_agent\studio_state.py',
    'local_agent\studio_server.py',
    'local_agent\studio_approval.py',
    'local_agent\poller.py',
    'local_agent\prompt_interpreter.py',
    'local_agent\studio_jobs.py',
    'local_agent\studio_blender_scene.py',
    'local_agent\studio_static\index.html',
    'local_agent\studio_static\style.css',
    'local_agent\studio_static\app.js',
    'tests\test_studio.py',
    'tests\test_studio_approval.py',
    'tests\test_prompt_pipeline.py',
    'tests\test_studio_assembly.py',
    'tests\test_studio_jobs_cancellation.py',
    'tests\test_studio_live_blender.py',
    'run_blender_studio.bat',
    'rollback_blender_studio.ps1',
    'docs\studio_ui_release.md'
)
$Backup = Join-Path $Target ("backup-studio-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-" + [guid]::NewGuid().ToString("N").Substring(0,8))
foreach ($Name in $Names) {
    $From = Join-Path $Source $Name
    if (!(Test-Path $From -PathType Leaf)) { throw "Файл отсутствует в архиве: $Name" }
}
New-Item -ItemType Directory -Path $Backup -Force | Out-Null
$NewFiles = @()

foreach ($Name in $Names) {
    $From = Join-Path $Source $Name

    $Dest = Join-Path $Target $Name
    if (Test-Path $Dest) {
        $Saved = Join-Path $Backup $Name
        New-Item -ItemType Directory -Path (Split-Path $Saved) -Force | Out-Null
        Copy-Item $Dest $Saved -Force
    } else { $NewFiles += $Name }
}
$NewFiles | Set-Content -Path (Join-Path $Backup 'new-files.txt') -Encoding UTF8
foreach ($Name in $Names) {
    $Dest = Join-Path $Target $Name
    New-Item -ItemType Directory -Path (Split-Path $Dest) -Force | Out-Null
    Copy-Item (Join-Path $Source $Name) $Dest -Force
    Write-Host "Установлено: $Name"
}
Write-Host "Резервные копии прежних файлов: $Backup" -ForegroundColor Cyan
Write-Host "Запуск: $Target\run_blender_studio.bat" -ForegroundColor Green

Write-Host "Откат: powershell -ExecutionPolicy Bypass -File `"$Target\rollback_blender_studio.ps1`" -Target `"$Target`" -Backup `"$Backup`""
