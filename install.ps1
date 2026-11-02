# STELLA CODER + Vibing AI Studio installer for Windows (PowerShell 5.1+ and pwsh).
# This file is intentionally ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the
# ANSI code page, which corrupts non-ASCII text. All user-facing text lives in install.mjs.
#   powershell -ExecutionPolicy Bypass -File install.ps1            interactive
#   powershell -ExecutionPolicy Bypass -File install.ps1 --stella   only the terminal agent
#   powershell -ExecutionPolicy Bypass -File install.ps1 --studio   only the studio
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Show-NodeHelp {
  Write-Host "Node.js 20.18+ is required (22 LTS recommended)." -ForegroundColor Yellow
  Write-Host "  Install: winget install OpenJS.NodeJS.LTS   (or download from https://nodejs.org)"
  Write-Host "  Then open a NEW PowerShell window and run this installer again."
  Write-Host "  Optional, for the Docker router mode: winget install Docker.DockerDesktop"
  exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Show-NodeHelp }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Show-NodeHelp }

$raw = (& node --version) -replace '^v', ''
$parts = $raw.Split('.')
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -lt 20 -or ($major -eq 20 -and $minor -lt 18)) {
  Write-Host "Found Node.js $raw" -ForegroundColor Yellow
  Show-NodeHelp
}

& node install.mjs @args
exit $LASTEXITCODE
