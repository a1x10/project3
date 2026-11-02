// Warns (non-blocking) when a written file looks like it contains a secret.
let d = '';
process.stdin.on('data', (c) => (d += c)).on('end', () => {
  const input = JSON.parse(d).tool_input ?? {};
  const text = String(input.content ?? input.new_string ?? '');
  if (/(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)/.test(text)) {
    process.stdout.write(JSON.stringify({ decision: 'block', reason: 'The change appears to contain a secret. Remove it and use environment variables.' }));
  }
});
