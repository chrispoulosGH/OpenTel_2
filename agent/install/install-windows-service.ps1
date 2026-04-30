# ============================================================
# install-windows-service.ps1
# Registers the OTel agent as a Windows Service using sc.exe
# ============================================================
# Prerequisites:
#   1. otel-agent.exe built for windows/amd64
#   2. config-windows.yaml in the same directory
#   3. Run this script as Administrator
# ============================================================

param(
    [string]$InstallDir  = "C:\Program Files\otel-agent",
    [string]$ServiceName = "otel-agent",
    [string]$CollectorEndpoint = "collector.example.com:4317",
    [string]$Environment = "dev"
)

$ErrorActionPreference = "Stop"

# --- Create install directory ---
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "Created $InstallDir"
}

# --- Copy files ---
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$ScriptDir\otel-agent.exe"       "$InstallDir\otel-agent.exe" -Force
Copy-Item "$ScriptDir\config-windows.yaml"   "$InstallDir\config.yaml"   -Force
Write-Host "Copied agent binary and config to $InstallDir"

# --- Set machine-level environment variables for the agent ---
[System.Environment]::SetEnvironmentVariable("CENTRAL_COLLECTOR_ENDPOINT", $CollectorEndpoint, "Machine")
[System.Environment]::SetEnvironmentVariable("ENVIRONMENT", $Environment, "Machine")
Write-Host "Set env vars: CENTRAL_COLLECTOR_ENDPOINT=$CollectorEndpoint, ENVIRONMENT=$Environment"

# --- Register Windows Service ---
$exePath = "`"$InstallDir\otel-agent.exe`" --config `"$InstallDir\config.yaml`""

# Remove existing service if present
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping existing service..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 2
}

& sc.exe create $ServiceName binPath= $exePath start= delayed-auto DisplayName= "OpenTelemetry Agent"
& sc.exe description $ServiceName "Lightweight OTel host-metrics agent"
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000

Write-Host "Service '$ServiceName' registered."

# --- Start the service ---
Start-Service -Name $ServiceName
Write-Host "Service '$ServiceName' started."
Write-Host ""
Write-Host "Verify with:  Get-Service $ServiceName"
Write-Host "Logs:          Event Viewer > Application log"
