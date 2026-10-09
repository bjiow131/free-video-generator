[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$TaskName = "AIStudio Local Agent"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'. Local files, logs, and credentials were not deleted."
} else {
    Write-Host "Scheduled task '$TaskName' was not registered."
}
