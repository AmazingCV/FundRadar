$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $ProjectRoot "logs\daily_runner"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogFile = Join-Path $LogDir "fundradar_weekly_deep_$Timestamp.log"
$CommandArgs = @("scripts/run_daily_all.py", "--limit", "1500")

function Write-RunLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    $line | Tee-Object -FilePath $LogFile -Append
}

$ExitCode = 1
try {
    Set-Location -LiteralPath $ProjectRoot
    Write-RunLog "FundRadar weekly deep runner started"
    Write-RunLog "Working directory: $ProjectRoot"
    Write-RunLog "Command: python $($CommandArgs -join ' ')"
    & python @CommandArgs 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ExitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }
}
catch {
    Write-RunLog "PowerShell error: $($_.Exception.Message)"
    $ExitCode = 1
}
finally {
    Write-RunLog "FundRadar weekly deep runner finished"
    Write-RunLog "Exit code: $ExitCode"
}

exit $ExitCode
