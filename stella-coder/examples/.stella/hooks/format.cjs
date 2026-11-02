// PostToolUse hook: format the file the agent just changed (if prettier is installed).
const { execFileSync } = require('node:child_process');
let data = '';
process.stdin.on('data', (c) => (data += c)).on('end', () => {
  const file = JSON.parse(data).tool_input?.file_path;
  if (!file || !/\.(js|jsx|ts|tsx|json|css|md)$/.test(file)) return;
  try {
    execFileSync('npx', ['--no-install', 'prettier', '--write', file], { stdio: 'ignore', shell: process.platform === 'win32' });
  } catch {
    /* prettier not installed: ignore */
  }
});
