# Build the Sourabh OS ISO on Windows with Docker Desktop (WSL2 backend).
# Usage (PowerShell, from the project folder):
#   .\iso\build-in-docker.ps1                                  # default: qwen2.5:0.5b preloaded
#   .\iso\build-in-docker.ps1 -Models "llama3.2:3b qwen2.5:7b" # bake bigger models into the ISO
#   .\iso\build-in-docker.ps1 -Models "" -Nvidia -AiServer     # GPU driver, serve AI to the LAN
#   .\iso\build-in-docker.ps1 -NoChrome                        # leave Google Chrome out
param([string]$Models = "qwen2.5:0.5b", [switch]$Nvidia, [switch]$AiServer, [switch]$NoChrome)
# Docker writes progress and harmless warnings to stderr; Windows PowerShell would
# treat those as fatal errors under "Stop", so we check exit codes ourselves instead.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Fail($msg) { Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

# 1) Is Docker installed and its engine running?
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed. Run:  winget install -e --id Docker.DockerDesktop"
}
$null = cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Fail "Docker Desktop is not running. Open Docker Desktop from the Start menu, wait for 'Engine running', then run this script again."
}

# 2) Build the builder image, then the ISO
cmd /c "docker build -t sourabhos-builder iso 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "building the Docker image failed (see messages above)" }

$envs = "-e PRELOAD_MODELS=`"$Models`" -e NVIDIA=$([int]$Nvidia.IsPresent) -e AI_SERVER=$([int]$AiServer.IsPresent) -e CHROME=$(1 - [int]$NoChrome.IsPresent)"
cmd /c "docker run --rm --privileged $envs -v `"${PWD}:/src`" sourabhos-builder 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "the ISO build failed. The full log is in out\build.log - send the last 30 lines for help." }

$iso = Join-Path $PWD "out\sourabhos-amd64.iso"
if (-not (Test-Path $iso)) { Fail "the build finished but $iso was not created. Check out\build.log." }
Write-Host "`nISO ready: $iso ($([math]::Round((Get-Item $iso).Length / 1GB, 2)) GB)" -ForegroundColor Green
Write-Host "Next (Administrator PowerShell):  .\iso\create-hyperv-vm.ps1 -Iso .\out\sourabhos-amd64.iso"
