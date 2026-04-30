# stop-agent.ps1 - Stop the OTel agent
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-agent.ps1

$PidFile = "C:\code\openTel_2\agent\agent-pid.json"

if (-not (Test-Path $PidFile)) {
    # Fallback: find agent by command line
    $agentProc = Get-Process otelcol-contrib -ErrorAction SilentlyContinue | Where-Object {
        (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like '*config-local-test*'
    }
    if ($agentProc) {
        Write-Host "Stopping agent (PID $($agentProc.Id)) ..."
        Stop-Process -Id $agentProc.Id -Force
        Write-Host "Agent stopped."
    } else {
        Write-Host "Agent is not running."
    }
    exit 0
}

$info = Get-Content $PidFile | ConvertFrom-Json
$procId = $info.agent

if ($procId) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping agent (PID $procId) ..."
        Stop-Process -Id $procId -Force
        Write-Host "Agent stopped."
    } else {
        Write-Host "Agent (PID $procId) already stopped."
    }
} else {
    Write-Host "No agent PID found in $PidFile."
}

Remove-Item $PidFile -ErrorAction SilentlyContinue
