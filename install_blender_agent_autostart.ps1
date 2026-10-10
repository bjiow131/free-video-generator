$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$target = Join-Path $root 'run_blender_agent.bat'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'run_blender_agent.bat was not found beside this installer.' }
$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'Blender Work Agent.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Start the local Blender Work Agent; no remote connection.'
$shortcut.WindowStyle = 1
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
if (Test-Path -LiteralPath $blender) { $shortcut.IconLocation = $blender + ',0' }
$shortcut.Save()
Write-Host ''
Write-Host 'Autostart installed for the current Windows user.'
Write-Host 'At sign-in, the agent console will open and ask before creating a scene.'
Write-Host 'Blender GUI opens when you confirm a Blender task.'
Write-Host ('Shortcut: ' + $shortcutPath)
if ($env:BLENDER_AGENT_AUTOSTART_SILENT -ne '1') { Read-Host 'Press Enter to close' }
