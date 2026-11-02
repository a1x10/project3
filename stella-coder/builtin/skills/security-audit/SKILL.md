---
name: security-audit
description: Security review of code and configuration — injection, authn/authz, secrets, path traversal, SSRF, XSS, dependency and supply-chain risks.
when_to_use: security review requests, handling untrusted input, auth code, before releases
---
# Security audit

Work read-only unless asked to fix. For each finding report: severity (critical/high/medium/low), file:line, attacker-controlled input → sink path, concrete exploit scenario, fix.

Checklist:
- Injection: SQL (string-built queries), OS command (`exec`, `shell=True`, backticks), template, LDAP, NoSQL operators, `eval`/dynamic imports.
- Path traversal & file handling: user input in file paths without normalization + root check; zip-slip; unsafe temp files; symlink following.
- SSRF: server-side fetches of user URLs without allowlist; access to metadata IPs.
- AuthN/AuthZ: missing auth on routes, IDOR (no ownership check), privilege escalation, JWT verification (alg none, missing exp), session fixation, weak password hashing (use bcrypt/argon2).
- XSS/CSRF: unescaped output, `dangerouslySetInnerHTML`/`v-html`, missing CSRF protection on cookie-auth state changes, permissive CORS with credentials.
- Secrets: keys/tokens in code, logs, error messages, client bundles, committed .env files.
- Crypto: home-made crypto, ECB, static IVs, `Math.random` for tokens.
- Deserialization: pickle/yaml.load/Java serialization of untrusted data.
- Dependencies: known-vulnerable versions (`npm audit`, `pip-audit`), typosquats, install scripts.
Avoid theoretical noise: only report issues with a plausible path from untrusted input.
