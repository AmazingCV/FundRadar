$ErrorActionPreference = "Stop"

$TaskName = "FundRadar Daily Report"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $ProjectRoot "logs\daily_runner"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

Write-Host "Task name: $TaskName"

if ($null -eq $Task) {
    Write-Host "Exists: false"
}
else {
    $Info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Exists: true"
    Write-Host "Enabled: $($Task.State -ne 'Disabled')"
    Write-Host "State: $($Task.State)"
    Write-Host "Next run time: $($Info.NextRunTime)"
    Write-Host "Last run time: $($Info.LastRunTime)"
    Write-Host "Last run result: $($Info.LastTaskResult)"
    Write-Host "WakeToRun: $($Task.Settings.WakeToRun)"
}

if (Test-Path -LiteralPath $LogDir) {
    $LatestLog = Get-ChildItem -LiteralPath $LogDir -Filter "*.log" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -ne $LatestLog) {
        Write-Host "Latest log: $($LatestLog.FullName)"
    }
    else {
        Write-Host "Latest log: none"
    }
}
else {
    Write-Host "Latest log: log directory does not exist"
}
