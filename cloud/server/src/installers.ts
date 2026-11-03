import fs from 'node:fs';
import path from 'node:path';

/** Newest STELLA CODER package (stella-coder*.tgz) the owner put into the downloads folder. */
export function stellaPackage(downloadsDir: string): string | null {
  try {
    const files = fs
      .readdirSync(downloadsDir)
      .filter((f) => /^stella-coder.*\.tgz$/i.test(f))
      .map((f) => ({ f, t: fs.statSync(path.join(downloadsDir, f)).mtimeMs }))
      .sort((a, b) => b.t - a.t);
    return files[0]?.f ?? null;
  } catch {
    return null;
  }
}

/**
 * Windows installer: `irm https://server/install.ps1 | iex`.
 * ASCII only — Windows PowerShell 5.1 reads scripts in the ANSI code page.
 */
export function installPs1(publicUrl: string, pkg: string | null): string {
  const pkgUrl = pkg ? `${publicUrl}/downloads/${encodeURIComponent(pkg)}` : '';
  return `# STELLA CODER installer for ${publicUrl}
$ErrorActionPreference = 'Continue'
# npm.cmd / stella-coder.cmd: the .ps1 shims are blocked by the default execution policy
$Server = '${publicUrl}'
$Package = '${pkgUrl}'
function Say($t) { Write-Host "==> $t" -ForegroundColor Magenta }
if (-not $Package) { Write-Host 'The server has no STELLA CODER package yet (ask the administrator).' -ForegroundColor Red; return }

function Get-NodeMajor { try { [int]((node -v) -replace '^v(\\d+).*', '$1') } catch { 0 } }
if ((Get-NodeMajor) -lt 20) {
  Say 'Installing Node.js LTS (winget)...'
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements --silent | Out-Host
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  }
  if ((Get-NodeMajor) -lt 20) { Write-Host 'Node.js 20+ is required: install the LTS from https://nodejs.org and run this command again.' -ForegroundColor Red; return }
}

Say 'Installing STELLA CODER...'
npm.cmd install -g $Package --no-audit --no-fund | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host 'npm install failed (see above).' -ForegroundColor Red; return }
$npmBin = (npm.cmd prefix -g).Trim()
if ($env:Path -notlike "*$npmBin*") { $env:Path = "$npmBin;$env:Path" }

Say 'Sign in: confirm the login in Telegram'
stella-coder.cmd login $Server
Write-Host ''
Write-Host 'Done. Open a project folder and run:  stella-coder' -ForegroundColor Green
`;
}

/** Linux/macOS installer: `curl -fsSL https://server/install.sh | bash`. */
export function installSh(publicUrl: string, pkg: string | null): string {
  const pkgUrl = pkg ? `${publicUrl}/downloads/${encodeURIComponent(pkg)}` : '';
  return `#!/usr/bin/env bash
# STELLA CODER installer for ${publicUrl}
set -euo pipefail
SERVER='${publicUrl}'
PACKAGE='${pkgUrl}'
say() { printf '\\033[1;35m==>\\033[0m %s\\n' "$*"; }
die() { printf '\\033[1;31m%s\\033[0m\\n' "$*" >&2; exit 1; }
[ -n "$PACKAGE" ] || die "На сервере ещё нет пакета STELLA CODER — обратитесь к администратору."
major=$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\\1/' || echo 0)
[ "\${major:-0}" -ge 20 ] 2>/dev/null || die "Нужен Node.js 20+: https://nodejs.org (Ubuntu: curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs; macOS: brew install node@22)"

say "Устанавливаю STELLA CODER…"
PREFIX_ARGS=()
if [ ! -w "$(npm prefix -g)/lib" ] && [ "$(id -u)" != 0 ]; then
  PREFIX_ARGS=(--prefix "$HOME/.local")
  export PATH="$HOME/.local/bin:$PATH"
fi
npm install -g \${PREFIX_ARGS[@]+"\${PREFIX_ARGS[@]}"} "$PACKAGE" --no-audit --no-fund

say "Вход: подтвердите его в Telegram"
stella-coder login "$SERVER"
echo
printf '\\033[1;32mГотово.\\033[0m Откройте папку проекта и запустите: stella-coder\\n'
if [ \${#PREFIX_ARGS[@]} -gt 0 ]; then echo "Если команда не найдена, добавьте в PATH: export PATH=\\"\\$HOME/.local/bin:\\$PATH\\""; fi
`;
}
