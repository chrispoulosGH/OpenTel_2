# ============================================================
# start-native.ps1
# Starts OTel Collector, Prometheus, and Grafana as background
# processes on Windows (no Docker required).
# ============================================================
# Prerequisites:  Run setup-native.ps1 first.
# Usage:          .\start-native.ps1
# Stop:           .\stop-native.ps1
# ============================================================

param(
    [string]$BinDir = "$PSScriptRoot\bin"
)

$ErrorActionPreference = "Stop"
$CentralDir = $PSScriptRoot

# --- Locate binaries ---
$OtelExe = Get-ChildItem "$BinDir\otelcol-contrib" -Filter "otelcol-contrib.exe" -Recurse | Select-Object -First 1
$PromExe = Get-ChildItem "$BinDir\prometheus"       -Filter "prometheus.exe"      -Recurse | Select-Object -First 1
$GrafDir = Get-ChildItem "$BinDir\grafana"           -Directory                   -Recurse | Where-Object { Test-Path "$($_.FullName)\bin\grafana-server.exe" } | Select-Object -First 1

if (-not $OtelExe) { Write-Error "otelcol-contrib.exe not found. Run setup-native.ps1 first."; exit 1 }
if (-not $PromExe) { Write-Error "prometheus.exe not found. Run setup-native.ps1 first."; exit 1 }
if (-not $GrafDir) { Write-Error "grafana-server.exe not found. Run setup-native.ps1 first."; exit 1 }

$GrafExe = "$($GrafDir.FullName)\bin\grafana-server.exe"

# --- PID file for stop script ---
$PidFile = "$BinDir\pids.json"

Write-Host "Starting Prometheus ..."
$promArgs = @(
    "--config.file=$CentralDir\prometheus.yaml"
    "--web.enable-remote-write-receiver"
    "--storage.tsdb.retention.time=15d"
    "--storage.tsdb.path=$BinDir\prometheus-data"
)
$promProc = Start-Process -FilePath $PromExe.FullName -ArgumentList $promArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($promProc.Id) — http://localhost:9090"

Write-Host "Starting OTel Collector ..."
$otelArgs = @("--config", "$CentralDir\collector-config-native.yaml")
$otelProc = Start-Process -FilePath $OtelExe.FullName -ArgumentList $otelArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($otelProc.Id) — gRPC :4317, HTTP :4318, health :13133"

Write-Host "Starting Grafana ..."
$grafArgs = @(
    "--homepath", $GrafDir.FullName
    "--config", "$($GrafDir.FullName)\conf\defaults.ini"
    "cfg:paths.provisioning=$CentralDir\grafana\provisioning-native"
    "cfg:paths.data=$BinDir\grafana-data"
    "cfg:security.admin_user=admin"
    "cfg:security.admin_password=admin"
)
$grafProc = Start-Process -FilePath $GrafExe -ArgumentList $grafArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($grafProc.Id) — http://localhost:3000 (admin / admin)"

# --- Save PIDs ---
$pids = @{
    prometheus     = $promProc.Id
    otelcollector  = $otelProc.Id
    grafana        = $grafProc.Id
}
$pids | ConvertTo-Json | Set-Content $PidFile

Write-Host ""
Write-Host "====================================="
Write-Host "Central stack running."
Write-Host "  Prometheus:     http://localhost:9090"
Write-Host "  Grafana:        http://localhost:3000"
Write-Host "  Collector gRPC: localhost:4317"
Write-Host "  Collector HTTP: localhost:4318"
Write-Host ""
Write-Host "Stop with:  .\stop-native.ps1"
Write-Host "====================================="
