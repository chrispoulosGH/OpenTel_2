# setup-from-downloads.ps1
# Extracts pre-downloaded archives into central\bin\
# Run from: C:\code\openTel_2\central
# Usage:    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-from-downloads.ps1

$ErrorActionPreference = "Stop"

$BaseDir     = "C:\code\openTel_2\central"
$DownloadDir = "$BaseDir\downloads"
$BinDir      = "$BaseDir\bin"

$OtelArchive  = "$DownloadDir\otelcol-contrib_0.120.0_windows_amd64.tar.gz"
$PromArchive  = "$DownloadDir\prometheus-2.53.0.windows-amd64.zip"
$TempoArchive = "$DownloadDir\tempo_2.5.0_windows_amd64.tar.gz"
$GrafArchive  = "$DownloadDir\grafana-11.1.0.windows-amd64.zip"
$LokiArchive  = Get-ChildItem $DownloadDir -Filter "loki*windows*amd64*.zip" -File -ErrorAction SilentlyContinue | Select-Object -First 1

Write-Host "BaseDir:     $BaseDir"
Write-Host "DownloadDir: $DownloadDir"
Write-Host "BinDir:      $BinDir"
Write-Host ""

# Check archives exist
$allGood = $true
foreach ($f in @($OtelArchive, $PromArchive, $TempoArchive, $GrafArchive)) {
    if (Test-Path $f) {
        Write-Host "[OK] Found: $(Split-Path $f -Leaf)"
    } else {
        Write-Host "[MISSING] $f" -ForegroundColor Red
        $allGood = $false
    }
}
if (-not $allGood) { Write-Host "Aborting - missing archives." -ForegroundColor Red; exit 1 }

Write-Host ""

# Create bin dir
if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
}

# --- OTel Collector (tar.gz) ---
$OtelDir = "$BinDir\otelcol-contrib"
if (Test-Path $OtelDir) {
    Write-Host "[otelcol-contrib] Already exists - skipping."
} else {
    Write-Host "[otelcol-contrib] Extracting..."
    New-Item -ItemType Directory -Path $OtelDir -Force | Out-Null
    tar -xzf $OtelArchive -C $OtelDir
    Write-Host "[otelcol-contrib] Done."
}

# --- Prometheus (zip) ---
$PromDir = "$BinDir\prometheus"
Write-Host "[debug] PromDir = $PromDir"
if (Test-Path $PromDir) {
    Write-Host "[prometheus] Already exists - skipping."
} else {
    Write-Host "[prometheus] Extracting..."
    $tempDir = "$BinDir\_tmp_prom"
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
    Expand-Archive -Path $PromArchive -DestinationPath $tempDir -Force
    New-Item -ItemType Directory -Path $PromDir -Force | Out-Null
    # Flatten single subfolder
    $sub = Get-ChildItem $tempDir
    if ($sub.Count -eq 1 -and $sub[0].PSIsContainer) {
        Get-ChildItem $sub[0].FullName | Move-Item -Destination $PromDir -Force
    } else {
        $sub | Move-Item -Destination $PromDir -Force
    }
    Remove-Item $tempDir -Recurse -Force
    Write-Host "[prometheus] Done."
}

# --- Tempo (tar.gz) ---
$TempoDir = "$BinDir\tempo"
Write-Host "[debug] TempoDir = $TempoDir"
if (Test-Path $TempoDir) {
    Write-Host "[tempo] Already exists - skipping."
} else {
    Write-Host "[tempo] Extracting..."
    New-Item -ItemType Directory -Path $TempoDir -Force | Out-Null
    tar -xzf $TempoArchive -C $TempoDir
    Write-Host "[tempo] Done."
}

# --- Grafana (zip) ---
$GrafDir = "$BinDir\grafana"
Write-Host "[debug] GrafDir = $GrafDir"
if (Test-Path $GrafDir) {
    Write-Host "[grafana] Already exists - skipping."
} else {
    Write-Host "[grafana] Extracting..."
    $tempDir = "$BinDir\_tmp_graf"
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
    Expand-Archive -Path $GrafArchive -DestinationPath $tempDir -Force
    New-Item -ItemType Directory -Path $GrafDir -Force | Out-Null
    $sub = Get-ChildItem $tempDir
    if ($sub.Count -eq 1 -and $sub[0].PSIsContainer) {
        Get-ChildItem $sub[0].FullName | Move-Item -Destination $GrafDir -Force
    } else {
        $sub | Move-Item -Destination $GrafDir -Force
    }
    Remove-Item $tempDir -Recurse -Force
    Write-Host "[grafana] Done."
}

# --- Loki (zip, optional) ---
$LokiDir = "$BinDir\loki"
if (Test-Path $LokiDir) {
    Write-Host "[loki] Already exists - skipping."
} elseif ($LokiArchive) {
    Write-Host "[loki] Extracting from $($LokiArchive.Name)..."
    $tempDir = "$BinDir\_tmp_loki"
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
    Expand-Archive -Path $LokiArchive.FullName -DestinationPath $tempDir -Force
    New-Item -ItemType Directory -Path $LokiDir -Force | Out-Null
    $sub = Get-ChildItem $tempDir
    if ($sub.Count -eq 1 -and $sub[0].PSIsContainer) {
        Get-ChildItem $sub[0].FullName | Move-Item -Destination $LokiDir -Force
    } else {
        $sub | Move-Item -Destination $LokiDir -Force
    }
    Remove-Item $tempDir -Recurse -Force
    Write-Host "[loki] Done."
} else {
    Write-Host "[loki] Archive not found in downloads (optional). Add loki*windows*amd64*.zip to enable native Loki startup." -ForegroundColor Yellow
}

# --- Data directories ---
foreach ($d in @("prometheus-data", "grafana-data", "tempo-data", "tempo-wal", "tempo-metrics-wal", "loki-data")) {
    $p = "$BinDir\$d"
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
    }
}

# --- Verify ---
Write-Host ""
Write-Host "Verifying binaries..."
$otelExe  = Get-ChildItem $OtelDir -Filter "otelcol-contrib.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$promExe  = Get-ChildItem $PromDir -Filter "prometheus.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$tempoExe = Get-ChildItem $TempoDir -Filter "tempo.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$grafExe  = Get-ChildItem $GrafDir -Filter "grafana-server.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$lokiExe  = Get-ChildItem $LokiDir -Filter "*.exe" -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^loki" } | Select-Object -First 1

$ok = $true
if ($otelExe)  { Write-Host "  [OK] $($otelExe.FullName)" -ForegroundColor Green }
else           { Write-Host "  [MISSING] otelcol-contrib.exe" -ForegroundColor Red; $ok = $false }
if ($promExe)  { Write-Host "  [OK] $($promExe.FullName)" -ForegroundColor Green }
else           { Write-Host "  [MISSING] prometheus.exe" -ForegroundColor Red; $ok = $false }
if ($tempoExe) { Write-Host "  [OK] $($tempoExe.FullName)" -ForegroundColor Green }
else           { Write-Host "  [MISSING] tempo.exe" -ForegroundColor Red; $ok = $false }
if ($grafExe)  { Write-Host "  [OK] $($grafExe.FullName)" -ForegroundColor Green }
else           { Write-Host "  [MISSING] grafana-server.exe" -ForegroundColor Red; $ok = $false }
if ($lokiExe)  { Write-Host "  [OK] $($lokiExe.FullName)" -ForegroundColor Green }
else           { Write-Host "  [WARN] Loki executable missing (logs in Grafana require Loki)." -ForegroundColor Yellow }

Write-Host ""
if ($ok) {
    Write-Host "Setup complete. Run: .\start-native.ps1" -ForegroundColor Green
} else {
    Write-Host "Some binaries missing - check output above." -ForegroundColor Red
    exit 1
}
