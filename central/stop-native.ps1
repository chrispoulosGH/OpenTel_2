# ============================================================
# stop-native.ps1
# Stops the native central stack processes started by
# start-native.ps1.
# ============================================================

param(
    [string]$BinDir = "$PSScriptRoot\bin"
)

$PidFile = "$BinDir\pids.json"

if (-not (Test-Path $PidFile)) {
    Write-Host "No PID file found at $PidFile — nothing to stop."
    exit 0
}

$pids = Get-Content $PidFile | ConvertFrom-Json

foreach ($svc in @("otelcollector", "prometheus", "grafana")) {
    $pid = $pids.$svc
    if ($pid) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping $svc (PID $pid) ..."
            Stop-Process -Id $pid -Force
        } else {
            Write-Host "$svc (PID $pid) already stopped."
        }
    }
}

Remove-Item $PidFile -ErrorAction SilentlyContinue
Write-Host "Central stack stopped."
