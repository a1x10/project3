#!/usr/bin/env bash
# STELLA CODER + Vibing AI Studio installer (Linux / macOS / WSL / Git Bash).
#   ./install.sh            interactive
#   ./install.sh --stella   only the terminal agent      ./install.sh --studio   only the studio
#   ./install.sh --yes      non-interactive
set -euo pipefail
cd "$(dirname "$0")"

need_node() {
  echo "Нужен Node.js 20.18+ (рекомендуется 22 LTS)." >&2
  echo "  macOS:  brew install node@22" >&2
  echo "  Linux:  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install 22" >&2
  echo "  или скачайте с https://nodejs.org" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || need_node
command -v npm >/dev/null 2>&1 || need_node
node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>20||(a===20&&b>=18)?0:1)' || need_node

exec node install.mjs "$@"
