# start-agent.ps1 - Stop any running agent, then start a fresh one
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\start-agent.ps1

$ErrorActionPreference = "Stop"

$BaseDir   = "C:\code\openTel_2"
$AgentDir  = "$BaseDir\agent"
$OtelExe   = "$BaseDir\central\bin\otelcol-contrib\otelcol-contrib.exe"
$ConfigFile = "$AgentDir\config-local-test.yaml"
$PidFile   = "$AgentDir\agent-pid.json"

# Verify binary and config exist
if (-not (Test-Path $OtelExe)) {
    Write-Host "NOT FOUND: $OtelExe" -ForegroundColor Red
    Write-Host "Run central\setup-from-downloads2.ps1 first."
    exit 1
}
if (-not (Test-Path $ConfigFile)) {
    Write-Host "NOT FOUND: $ConfigFile" -ForegroundColor Red
    exit 1
}

# --- Stop existing agent first ---
Write-Host "Checking for running agent ..."

$stopped = $false

# Try PID file first
if (Test-Path $PidFile) {
    $info = Get-Content $PidFile | ConvertFrom-Json
    $procId = $info.agent
    if ($procId) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Stopping existing agent (PID $procId) ..."
            Stop-Process -Id $procId -Force
            Start-Sleep -Seconds 1
            $stopped = $true
        }
    }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

# Fallback: find by command line
if (-not $stopped) {
    $agentProc = Get-Process otelcol-contrib -ErrorAction SilentlyContinue | Where-Object {
        (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -like '*config-local-test*'
    }
    if ($agentProc) {
        Write-Host "  Stopping existing agent (PID $($agentProc.Id)) ..."
        Stop-Process -Id $agentProc.Id -Force
        Start-Sleep -Seconds 1
    }
}

# --- Start agent ---
$env:NO_PROXY = "localhost,127.0.0.1"

Write-Host "Starting agent ..."
$agentArgs = @("--config", $ConfigFile)
$agentProc = Start-Process -FilePath $OtelExe -ArgumentList $agentArgs -PassThru -WindowStyle Hidden
Write-Host "  PID $($agentProc.Id) - health :13134, telemetry :8889"

# Save PID
@{ agent = $agentProc.Id } | ConvertTo-Json | Set-Content $PidFile
Write-Host "Agent started. PID saved to $PidFile"
