# ============================================================
# setup-native.ps1
# Downloads OTel Collector, Prometheus, and Grafana binaries
# for running the central stack natively on Windows.
# ============================================================
# Run once:  .\setup-native.ps1
# Then:      .\start-native.ps1
# ============================================================

param(
    [string]$BinDir = "$PSScriptRoot\bin"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# --- Versions (match docker-compose.yaml) ---
$OtelVersion       = "0.120.0"
$PrometheusVersion = "2.53.0"
$GrafanaVersion    = "11.1.0"

# --- Download URLs ---
$OtelUrl       = "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OtelVersion}/otelcol-contrib_${OtelVersion}_windows_amd64.tar.gz"
$PrometheusUrl = "https://github.com/prometheus/prometheus/releases/download/v${PrometheusVersion}/prometheus-${PrometheusVersion}.windows-amd64.zip"
$GrafanaUrl    = "https://dl.grafana.com/oss/release/grafana-${GrafanaVersion}.windows-amd64.zip"

# --- Helpers ---
function Download-AndExtract {
    param([string]$Url, [string]$OutDir, [string]$Label, [switch]$IsTarGz)

    # Derive a safe local filename from the URL
    $uri      = [System.Uri]$Url
    $fileName = $uri.Segments[-1]
    $dlPath   = Join-Path $env:TEMP $fileName

    if (Test-Path $OutDir) {
        Write-Host "[$Label] Already exists at $OutDir — skipping."
        return
    }

    Write-Host "[$Label] Downloading $fileName ..."
    Invoke-WebRequest -Uri $Url -OutFile $dlPath -UseBasicParsing

    if (-not (Test-Path $dlPath)) {
        Write-Error "[$Label] Download failed — $dlPath not found."
        return
    }

    Write-Host "[$Label] Extracting to $OutDir ..."
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    if ($IsTarGz) {
        & tar -xzf $dlPath -C $OutDir
    } else {
        $tempExtract = "$BinDir\_extract_$Label"
        if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force }
        Expand-Archive -Path $dlPath -DestinationPath $tempExtract -Force
        $inner = Get-ChildItem $tempExtract
        if ($inner.Count -eq 1 -and $inner[0].PSIsContainer) {
            Get-ChildItem $inner[0].FullName | Move-Item -Destination $OutDir -Force
        } else {
            $inner | Move-Item -Destination $OutDir -Force
        }
        Remove-Item $tempExtract -Recurse -Force
    }

    Remove-Item $dlPath -ErrorAction SilentlyContinue
    Write-Host "[$Label] Done."
}

# --- Create bin directory ---
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

# --- Download each component ---
Download-AndExtract -Url $OtelUrl       -OutDir "$BinDir\otelcol-contrib" -Label "otelcol-contrib" -IsTarGz
Download-AndExtract -Url $PrometheusUrl -OutDir "$BinDir\prometheus"      -Label "prometheus"
Download-AndExtract -Url $GrafanaUrl    -OutDir "$BinDir\grafana"         -Label "grafana"

# --- Create Prometheus data directory ---
$PromDataDir = "$BinDir\prometheus-data"
if (-not (Test-Path $PromDataDir)) {
    New-Item -ItemType Directory -Path $PromDataDir -Force | Out-Null
}

# --- Create Grafana data directory ---
$GrafDataDir = "$BinDir\grafana-data"
if (-not (Test-Path $GrafDataDir)) {
    New-Item -ItemType Directory -Path $GrafDataDir -Force | Out-Null
}

Write-Host ""
Write-Host "====================================="
Write-Host "Setup complete. Run: .\start-native.ps1"
Write-Host "====================================="
