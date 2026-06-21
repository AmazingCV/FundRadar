param(
    [string]$Time = "23:30"
)

$ErrorActionPreference = "Stop"

$TaskName = "FundRadar Daily Report"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunnerScript = Join-Path $ProjectRoot "scripts\run_fundradar_daily.ps1"

if (-not (Test-Path -LiteralPath $RunnerScript)) {
    throw "Runner script not found: $RunnerScript"
}

$At = [datetime]::ParseExact($Time, "HH:mm", $null)
$ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$RunnerScript`""
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArgs -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$UserId = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal

Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

Write-Host "Task registered or updated."
Write-Host "Task name: $TaskName"
Write-Host "Run time: $Time"
Write-Host "Script path: $RunnerScript"
Write-Host "WakeToRun: true"
Write-Host "Run manually: Start-ScheduledTask -TaskName `"$TaskName`""
