# ============================================================
# setup-from-downloads.ps1
# Extracts pre-downloaded OTel Collector, Prometheus, and
# Grafana archives into central\bin\.
# ============================================================
# 1. Download these files via your browser and save them to
#    central\downloads\:
#
#    - otelcol-contrib_0.120.0_windows_amd64.tar.gz
#      https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.120.0/otelcol-contrib_0.120.0_windows_amd64.tar.gz
#
#    - prometheus-2.53.0.windows-amd64.zip
#      https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.windows-amd64.zip
#
#    - grafana-11.1.0.windows-amd64.zip
#      https://dl.grafana.com/oss/release/grafana-11.1.0.windows-amd64.zip
#
# 2. Then run:  .\setup-from-downloads.ps1
# 3. Then run:  .\start-native.ps1
# ============================================================

param(
    [string]$DownloadDir,
    [string]$BinDir
)

$ErrorActionPreference = "Stop"

# Resolve script directory reliably
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
if (-not $ScriptDir) {
    $ScriptDir = Get-Location
}
if (-not $DownloadDir) { $DownloadDir = "$ScriptDir\downloads" }
if (-not $BinDir)      { $BinDir      = "$ScriptDir\bin" }

Write-Host "ScriptDir:   $ScriptDir"
Write-Host "DownloadDir: $DownloadDir"
Write-Host "BinDir:      $BinDir"

# --- Expected file names ---
$OtelArchive = Join-Path $DownloadDir "otelcol-contrib_0.120.0_windows_amd64.tar.gz"
$PromArchive = Join-Path $DownloadDir "prometheus-2.53.0.windows-amd64.zip"
$GrafArchive = Join-Path $DownloadDir "grafana-11.1.0.windows-amd64.zip"

# --- Verify all archives exist ---
$missing = @()
if (-not (Test-Path $OtelArchive)) { $missing += "otelcol-contrib_0.120.0_windows_amd64.tar.gz" }
if (-not (Test-Path $PromArchive)) { $missing += "prometheus-2.53.0.windows-amd64.zip" }
if (-not (Test-Path $GrafArchive)) { $missing += "grafana-11.1.0.windows-amd64.zip" }

if ($missing.Count -gt 0) {
    Write-Host "ERROR: Missing files in $DownloadDir :" -ForegroundColor Red
    foreach ($f in $missing) { Write-Host "  - $f" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Download them from:" -ForegroundColor Yellow
    Write-Host "  OTel Collector:  https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.120.0/otelcol-contrib_0.120.0_windows_amd64.tar.gz"
    Write-Host "  Prometheus:      https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.windows-amd64.zip"
    Write-Host "  Grafana:         https://dl.grafana.com/oss/release/grafana-11.1.0.windows-amd64.zip"
    Write-Host ""
    Write-Host "Save them to: $DownloadDir"
    exit 1
}

Write-Host "All archives found in $DownloadDir"

# --- Create bin directory ---
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

# --- Extract OTel Collector (tar.gz) ---
$OtelDir = Join-Path $BinDir "otelcol-contrib"
if (Test-Path $OtelDir) {
    Write-Host "[otelcol-contrib] Already extracted — skipping."
} else {
    Write-Host "[otelcol-contrib] Extracting ..."
    New-Item -ItemType Directory -Path $OtelDir -Force | Out-Null
    & tar -xzf $OtelArchive -C $OtelDir
    Write-Host "[otelcol-contrib] Done."
}

# --- Extract Prometheus (zip) ---
$PromDir = Join-Path $BinDir "prometheus"
if (Test-Path $PromDir) {
    Write-Host "[prometheus] Already extracted — skipping."
} else {
    Write-Host "[prometheus] Extracting ..."
    $tempProm = Join-Path $BinDir "_extract_prometheus"
    if (Test-Path $tempProm) { Remove-Item $tempProm -Recurse -Force }
    Expand-Archive -Path $PromArchive -DestinationPath $tempProm -Force
    # Flatten the single subfolder (prometheus-X.Y.Z.windows-amd64)
    New-Item -ItemType Directory -Path $PromDir -Force | Out-Null
    $inner = Get-ChildItem $tempProm
    if ($inner.Count -eq 1 -and $inner[0].PSIsContainer) {
        Get-ChildItem $inner[0].FullName | Move-Item -Destination $PromDir -Force
    } else {
        $inner | Move-Item -Destination $PromDir -Force
    }
    Remove-Item $tempProm -Recurse -Force
    Write-Host "[prometheus] Done."
}

# --- Extract Grafana (zip) ---
$GrafDir = Join-Path $BinDir "grafana"
if (Test-Path $GrafDir) {
    Write-Host "[grafana] Already extracted — skipping."
} else {
    Write-Host "[grafana] Extracting ..."
    $tempGraf = Join-Path $BinDir "_extract_grafana"
    if (Test-Path $tempGraf) { Remove-Item $tempGraf -Recurse -Force }
    Expand-Archive -Path $GrafArchive -DestinationPath $tempGraf -Force
    New-Item -ItemType Directory -Path $GrafDir -Force | Out-Null
    $inner = Get-ChildItem $tempGraf
    if ($inner.Count -eq 1 -and $inner[0].PSIsContainer) {
        Get-ChildItem $inner[0].FullName | Move-Item -Destination $GrafDir -Force
    } else {
        $inner | Move-Item -Destination $GrafDir -Force
    }
    Remove-Item $tempGraf -Recurse -Force
    Write-Host "[grafana] Done."
}

# --- Create data directories ---
foreach ($d in @("prometheus-data", "grafana-data")) {
    $p = Join-Path $BinDir $d
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
    }
}

# --- Verify binaries ---
Write-Host ""
Write-Host "Verifying binaries ..."
$otelExe = Get-ChildItem $OtelDir -Filter "otelcol-contrib.exe" -Recurse | Select-Object -First 1
$promExe = Get-ChildItem $PromDir -Filter "prometheus.exe" -Recurse | Select-Object -First 1
$grafExe = Get-ChildItem $GrafDir -Filter "grafana-server.exe" -Recurse | Select-Object -First 1

$ok = $true
if ($otelExe) { Write-Host "  [OK] $($otelExe.FullName)" -ForegroundColor Green }
else          { Write-Host "  [MISSING] otelcol-contrib.exe" -ForegroundColor Red; $ok = $false }

if ($promExe) { Write-Host "  [OK] $($promExe.FullName)" -ForegroundColor Green }
else          { Write-Host "  [MISSING] prometheus.exe" -ForegroundColor Red; $ok = $false }

if ($grafExe) { Write-Host "  [OK] $($grafExe.FullName)" -ForegroundColor Green }
else          { Write-Host "  [MISSING] grafana-server.exe" -ForegroundColor Red; $ok = $false }

Write-Host ""
if ($ok) {
    Write-Host "====================================" -ForegroundColor Green
    Write-Host "Setup complete. Run: .\start-native.ps1" -ForegroundColor Green
    Write-Host "====================================" -ForegroundColor Green
} else {
    Write-Host "Some binaries are missing — check extraction output above." -ForegroundColor Red
    exit 1
}
