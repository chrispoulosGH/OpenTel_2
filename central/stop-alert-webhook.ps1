# ============================================================
# stop-alert-webhook.ps1
# Stops the local HTTP webhook service for Grafana alerts.
# ============================================================

$ErrorActionPreference = "Stop"
$CentralDir = $PSScriptRoot
$PidFile = "$CentralDir\bin\alert-webhook-pid.json"

if (-not (Test-Path $PidFile)) {
    Write-Host "No webhook PID file found. Service may already be stopped."
    exit 0
}

try {
    $pidData = Get-Content $PidFile | ConvertFrom-Json
} catch {
    Write-Warning "Failed to parse PID file. Deleting file."
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

if (-not $pidData.pid) {
    Write-Warning "PID file does not contain a process ID. Deleting file."
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

$proc = Get-Process -Id $pidData.pid -ErrorAction SilentlyContinue
if ($proc) {
    Stop-Process -Id $pidData.pid -Force
    Write-Host "Stopped webhook service PID $($pidData.pid)."
} else {
    Write-Host "Process PID $($pidData.pid) is not running."
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Webhook service stopped."
