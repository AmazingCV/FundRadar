$ErrorActionPreference = "Stop"

$TaskName = "FundRadar Daily Report"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($null -eq $Task) {
    Write-Host "Task does not exist: $TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Task unregistered: $TaskName"
