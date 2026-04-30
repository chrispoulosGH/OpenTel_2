# start-native2.ps1 - Start the central stack natively
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\start-native2.ps1
# Stop:  powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-native2.ps1

$ErrorActionPreference = "Stop"

$BaseDir    = "C:\code\openTel_2\central"
$BinDir     = "$BaseDir\bin"

# Ensure local service-to-service calls are never sent through a corporate proxy.
$requiredNoProxyHosts = @("localhost", "127.0.0.1", "::1")
$machineNames = @()
if ($env:COMPUTERNAME) { $machineNames += $env:COMPUTERNAME }
try {
    $fqdn = [System.Net.Dns]::GetHostByName(($env:COMPUTERNAME)).HostName
    if ($fqdn) { $machineNames += $fqdn }
} catch {
    # FQDN lookup is best-effort only.
}
$requiredNoProxyHosts += ($machineNames | Select-Object -Unique)
$existingNoProxy = @()
if ($env:NO_PROXY) {
    $existingNoProxy = $env:NO_PROXY.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

foreach ($noProxyHost in $requiredNoProxyHosts) {
    if (-not ($existingNoProxy -contains $noProxyHost)) {
        $existingNoProxy += $noProxyHost
    }
}

$noProxyValue = ($existingNoProxy -join ",")
$env:NO_PROXY = $noProxyValue
$env:no_proxy = $noProxyValue

$OtelExe    = "$BinDir\otelcol-contrib\otelcol-contrib.exe"
$PromExe    = "$BinDir\prometheus\prometheus.exe"
$TempoExe   = "$BinDir\tempo\tempo.exe"
$GrafExe    = "$BinDir\grafana\bin\grafana-server.exe"
$GrafHome   = "$BinDir\grafana"
$LokiCfg    = "$BaseDir\loki-native.yaml"

$LokiExeObj = Get-ChildItem "$BinDir\loki" -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "^loki" } |
    Select-Object -First 1
$LokiExe = if ($LokiExeObj) { $LokiExeObj.FullName } else { $null }

$PidFile    = "$BinDir\pids.json"

# Verify binaries
foreach ($exe in @($OtelExe, $PromExe, $TempoExe, $GrafExe)) {
    if (-not (Test-Path $exe)) {
        Write-Host "NOT FOUND: $exe" -ForegroundColor Red
        Write-Host "Run setup-from-downloads2.ps1 first."
        exit 1
    }
}

if (-not (Test-Path $LokiCfg)) {
    Write-Host "NOT FOUND: $LokiCfg" -ForegroundColor Red
    Write-Host "Create loki-native.yaml or pull latest central scripts."
    exit 1
}

Write-Host "Starting Prometheus ..."
$promArgs = @(
    "--config.file=$BaseDir\prometheus.yaml",
    "--web.enable-remote-write-receiver",
    "--storage.tsdb.retention.time=15d",
    "--storage.tsdb.path=$BinDir\prometheus-data"
)
$promProc = Start-Process -FilePath $PromExe -ArgumentList $promArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($promProc.Id) - http://localhost:9090"

# Short pause to let Prometheus start before collector tries to write to it
Start-Sleep -Seconds 3

Write-Host "Starting Tempo ..."
$tempoArgs = "-config.file=$BaseDir\tempo.yaml"
$tempoProc = Start-Process -FilePath $TempoExe -ArgumentList $tempoArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($tempoProc.Id) - http://localhost:3200"

Start-Sleep -Seconds 2

if ($LokiExe) {
    Write-Host "Starting Loki ..."
    $lokiArgs = "-config.file=$LokiCfg"
    $lokiProc = Start-Process -FilePath $LokiExe -ArgumentList $lokiArgs -PassThru -WindowStyle Hidden
    Write-Host "  PID $($lokiProc.Id) - http://localhost:3100"
    Start-Sleep -Seconds 2
} else {
    Write-Host "Loki binary not found under $BinDir\loki; logs pipeline will fail until Loki is installed." -ForegroundColor Yellow
}

Write-Host "Starting OTel Collector ..."
$otelArgs = @("--config", "$BaseDir\collector-config-native.yaml")
$otelProc = Start-Process -FilePath $OtelExe -ArgumentList $otelArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($otelProc.Id) - gRPC :4317, HTTP :4318, health :13133"

Write-Host "Starting Grafana ..."
$grafArgs = @(
    "--homepath", $GrafHome,
    "--config", "$GrafHome\conf\defaults.ini",
    "cfg:paths.provisioning=$BaseDir\grafana\provisioning-native",
    "cfg:paths.data=$BinDir\grafana-data",
    "cfg:security.admin_user=admin",
    "cfg:security.admin_password=admin"
)
$grafProc = Start-Process -FilePath $GrafExe -ArgumentList $grafArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($grafProc.Id) - http://localhost:3000 (admin / admin)"

# Save PIDs
$pids = @{
    prometheus    = $promProc.Id
    tempo         = $tempoProc.Id
    otelcollector = $otelProc.Id
    grafana       = $grafProc.Id
}
if ($lokiProc) {
    $pids["loki"] = $lokiProc.Id
}
$pids | ConvertTo-Json | Set-Content $PidFile

Write-Host ""
Write-Host "====================================="
Write-Host "Central stack running."
Write-Host "  Prometheus:     http://localhost:9090"
Write-Host "  Tempo:          http://localhost:3200"
if ($lokiProc) {
    Write-Host "  Loki:           http://localhost:3100"
} else {
    Write-Host "  Loki:           not running (binary missing)"
}
Write-Host "  Grafana:        http://localhost:3000"
Write-Host "  Collector gRPC: localhost:4317"
Write-Host "  Collector HTTP: localhost:4318"
Write-Host ""
Write-Host "Stop with: powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-native2.ps1"
Write-Host "====================================="
