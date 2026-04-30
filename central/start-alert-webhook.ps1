# ============================================================
# start-alert-webhook.ps1
# Starts a local HTTP webhook service for Grafana alerts.
# ============================================================
# Usage: .\start-alert-webhook.ps1
# Stop:  .\stop-alert-webhook.ps1
# ============================================================

param(
    [int]$Port = 8088,
    [string]$BindHost = "127.0.0.1",
    [string]$AuthToken = "",
    [switch]$AutoIngest,
    [string]$BpmnFile = ""
)

$ErrorActionPreference = "Stop"
$CentralDir = $PSScriptRoot
$RepoRoot = Split-Path -Path $CentralDir -Parent
$ServiceScript = "$CentralDir\alert-webhook-service\server.py"
$PidFile = "$CentralDir\bin\alert-webhook-pid.json"
$LogFile = "$CentralDir\bin\alert-webhook\alerts.ndjson"

if (-not (Test-Path $ServiceScript)) {
    Write-Error "Webhook service script not found at $ServiceScript"
    exit 1
}

if (Test-Path $PidFile) {
    try {
        $existing = Get-Content $PidFile | ConvertFrom-Json
        if ($existing.pid) {
            $running = Get-Process -Id $existing.pid -ErrorAction SilentlyContinue
            if ($running) {
                Write-Host "Alert webhook already running (PID $($existing.pid))."
                Write-Host "Stop it first with .\stop-alert-webhook.ps1"
                exit 0
            }
        }
    } catch {
        Write-Warning "Could not parse existing PID file. Continuing."
    }
}

$venvPython = "$RepoRoot\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $PythonExe = $venvPython
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Error "Python executable not found. Activate .venv or install Python."
        exit 1
    }
    $PythonExe = $pythonCmd.Source
}

$env:WEBHOOK_LOG_FILE = $LogFile
if ($AuthToken) {
    $env:WEBHOOK_AUTH_TOKEN = $AuthToken
}
if ($AutoIngest) {
    $env:WEBHOOK_AUTO_INGEST = "true"
}
if ($BpmnFile) {
    $resolvedBpmn = Resolve-Path -Path $BpmnFile -ErrorAction Stop
    $env:WEBHOOK_BPMN_FILE = $resolvedBpmn.Path
}

$args = @($ServiceScript, "--host", $BindHost, "--port", "$Port", "--log-file", $LogFile)
if ($AuthToken) {
    $args += @("--auth-token", $AuthToken)
}
if ($AutoIngest) {
    $args += @("--auto-ingest")
}
if ($BpmnFile) {
    $args += @("--bpmn-file", $env:WEBHOOK_BPMN_FILE)
}

Write-Host "Starting alert webhook service ..."
$proc = Start-Process -FilePath $PythonExe -ArgumentList $args -PassThru -WindowStyle Hidden

$pidData = @{
    pid = $proc.Id
    host = $BindHost
    port = $Port
    started_at = (Get-Date).ToString("o")
    log_file = $LogFile
}
$pidData | ConvertTo-Json | Set-Content $PidFile

Write-Host "  PID $($proc.Id)"
Write-Host "  Health URL: http://$BindHost`:$Port/health"
Write-Host "  Grafana webhook URL: http://$BindHost`:$Port/grafana/alert"
Write-Host "  Event log: $LogFile"
if ($AutoIngest) {
    Write-Host "  Auto-ingest BPMN: $env:WEBHOOK_BPMN_FILE"
}
