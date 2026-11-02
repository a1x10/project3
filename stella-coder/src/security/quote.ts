/** Quote one argument for the given shell family so it is passed literally. */
export function shellQuote(arg: string, kind: 'posix' | 'powershell' | 'cmd' = process.platform === 'win32' ? 'powershell' : 'posix'): string {
  if (kind === 'posix') return `'${arg.replace(/'/g, `'\\''`)}'`;
  if (kind === 'powershell') return `'${arg.replace(/'/g, "''")}'`;
  if (/["%^&|<>]/.test(arg)) throw new Error(`Unsafe characters in argument for cmd.exe: ${arg}`);
  return `"${arg}"`;
}
