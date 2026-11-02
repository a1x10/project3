# STELLA CODER + Vibing AI Studio installer for Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File install.ps1            interactive
#   powershell -ExecutionPolicy Bypass -File install.ps1 --stella   only the terminal agent
#   powershell -ExecutionPolicy Bypass -File install.ps1 --studio   only the studio
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Need-Node {
  Write-Host "Нужен Node.js 20.18+ (рекомендуется 22 LTS)." -ForegroundColor Yellow
  Write-Host "  winget install OpenJS.NodeJS.LTS   (или скачайте с https://nodejs.org)"
  Write-Host "  Для режима Docker установите Docker Desktop: winget install Docker.DockerDesktop"
  exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Need-Node }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Need-Node }
node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>20||(a===20&&b>=18)?0:1)"
if ($LASTEXITCODE -ne 0) { Need-Node }

node install.mjs @args
exit $LASTEXITCODE
