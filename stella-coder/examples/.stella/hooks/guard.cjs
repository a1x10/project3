// PreToolUse hook: reads the tool call from stdin and blocks risky commands with exit code 2.
let data = '';
process.stdin.on('data', (c) => (data += c)).on('end', () => {
  const { tool_input: input } = JSON.parse(data);
  const cmd = String(input?.command ?? '');
  const rules = [
    [/\bterraform\s+apply\b/, 'terraform apply must be run by a human'],
    [/\bkubectl\s+(delete|apply)\b/, 'cluster changes are not allowed from the agent'],
    [/\bDROP\s+(TABLE|DATABASE)\b/i, 'destructive SQL is blocked'],
  ];
  for (const [re, why] of rules) {
    if (re.test(cmd)) {
      process.stderr.write(`Blocked: ${why}`);
      process.exit(2);
    }
  }
});
