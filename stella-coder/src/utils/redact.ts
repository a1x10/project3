/**
 * Secret detection & masking. Used for logs, transcripts shown to hooks, and memory writes.
 */
const PATTERNS: RegExp[] = [
  /sk-ant-[A-Za-z0-9_\-]{16,}/g, // Anthropic
  /sk-(?:proj-|or-v1-)?[A-Za-z0-9_\-]{20,}/g, // OpenAI / OpenRouter
  /gsk_[A-Za-z0-9]{20,}/g, // Groq
  /AIza[0-9A-Za-z_\-]{30,}/g, // Google
  /gh[pousr]_[A-Za-z0-9]{30,}/g, // GitHub
  /github_pat_[A-Za-z0-9_]{30,}/g,
  /xox[baprs]-[A-Za-z0-9-]{10,}/g, // Slack
  /AKIA[0-9A-Z]{16}/g, // AWS access key id
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
  /\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*["']?[^\s"']{8,}/gi,
];

export function containsSecret(text: string): boolean {
  return PATTERNS.some((re) => {
    re.lastIndex = 0;
    return re.test(text);
  });
}

export function redact(text: string): string {
  let out = text;
  for (const re of PATTERNS) {
    re.lastIndex = 0;
    out = out.replace(re, (m) => {
      const eq = m.search(/[:=]/);
      if (eq > 0 && /^[a-z_\- ]+[:=]/i.test(m)) return m.slice(0, eq + 1) + ' ***';
      return m.slice(0, 4) + '…' + '***';
    });
  }
  return out;
}

export function maskKey(key: string | undefined): string {
  if (!key) return '(not set)';
  if (key.length <= 8) return '***';
  return key.slice(0, 6) + '…' + key.slice(-4);
}
