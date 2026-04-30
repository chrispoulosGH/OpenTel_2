# stop-native2.ps1 - Stop the central stack
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-native2.ps1

$BinDir  = "C:\code\openTel_2\central\bin"
$PidFile = "$BinDir\pids.json"

# Map service names to one or more process names.
$ProcessNameMap = @{
    "otelcollector" = @("otelcol-contrib")
    "tempo"         = @("tempo")
    "loki"          = @("loki", "loki-windows-amd64")
    "prometheus"    = @("prometheus")
    "grafana"       = @("grafana", "grafana-server")
}

# Load PIDs from file if it exists
$pidsFromFile = @{}
if (Test-Path $PidFile) {
    $pidData = Get-Content $PidFile | ConvertFrom-Json
    foreach ($prop in $pidData.PSObject.Properties) {
        $pidsFromFile[$prop.Name] = $prop.Value
    }
}

$procsToStop = @()

# Check PIDs from file
foreach ($svc in @("otelcollector", "tempo", "loki", "prometheus", "grafana")) {
    $procId = $pidsFromFile[$svc]
    if ($procId) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            $procsToStop += @{ ServiceName = $svc; ProcessName = $proc.ProcessName; PID = $procId; FromFile = $true }
        }
    }
}

# Search for running processes by name
foreach ($svc in @("otelcollector", "tempo", "loki", "prometheus", "grafana")) {
    foreach ($procName in $ProcessNameMap[$svc]) {
        $runningProcs = Get-Process -Name $procName -ErrorAction SilentlyContinue

        foreach ($proc in $runningProcs) {
            $alreadyInList = $procsToStop | Where-Object { $_.PID -eq $proc.Id }

            if (-not $alreadyInList) {
                $procsToStop += @{ ServiceName = $svc; ProcessName = $proc.ProcessName; PID = $proc.Id; FromFile = $false }
            }
        }
    }
}

if ($procsToStop.Count -eq 0) {
    Write-Host "No running services found."
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    exit 0
}

# Display processes and stop them
foreach ($proc in $procsToStop) {
    $source = if ($proc.FromFile) { "(from PID file)" } else { "(found by process name)" }
    
    if (-not $proc.FromFile) {
        Write-Host "Found untracked process: $($proc.ServiceName) PID $($proc.PID) $source" -ForegroundColor Yellow
        $response = Read-Host "Stop this process? (y/n)"
        if ($response -ne "y") {
            Write-Host "  Skipped $($proc.ServiceName) (PID $($proc.PID))"
            continue
        }
    }
    
    Write-Host "Stopping $($proc.ServiceName) (PID $($proc.PID)) $source ..."
    Stop-Process -Id $proc.PID -Force -ErrorAction SilentlyContinue
}

Remove-Item $PidFile -ErrorAction SilentlyContinue
Write-Host "Central stack stopped."
