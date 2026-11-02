import { promises as fs } from 'node:fs';
import path from 'node:path';
import { exists, readJson } from '../utils/fsutil.js';
import type { ProjectIndex } from './index.js';

export interface ProjectProfile {
  root: string;
  name: string;
  languages: Array<{ lang: string; files: number }>;
  manifests: string[];
  frameworks: string[];
  packageManager?: string;
  entryPoints: string[];
  testDirs: string[];
  commands: { test?: string; build?: string; lint?: string; format?: string; typecheck?: string; run?: string };
  readme?: string;
  isGit: boolean;
  fileCount: number;
  topDirs: string[];
}

const MANIFESTS = ['package.json', 'pyproject.toml', 'requirements.txt', 'setup.py', 'Pipfile', 'go.mod', 'Cargo.toml', 'pom.xml', 'build.gradle', 'build.gradle.kts', 'composer.json', 'Gemfile', 'deno.json', 'CMakeLists.txt', 'Makefile', '*.csproj', '*.sln', 'pubspec.yaml', 'Dockerfile', 'docker-compose.yml'];

const JS_FRAMEWORKS: Record<string, string> = {
  react: 'React', next: 'Next.js', vue: 'Vue', nuxt: 'Nuxt', svelte: 'Svelte', '@sveltejs/kit': 'SvelteKit', '@angular/core': 'Angular', express: 'Express', fastify: 'Fastify', '@nestjs/core': 'NestJS', koa: 'Koa', vite: 'Vite', webpack: 'Webpack', electron: 'Electron', 'react-native': 'React Native', ink: 'Ink', jest: 'Jest', vitest: 'Vitest', mocha: 'Mocha', '@playwright/test': 'Playwright', cypress: 'Cypress', typescript: 'TypeScript', tailwindcss: 'Tailwind CSS', prisma: 'Prisma', 'drizzle-orm': 'Drizzle', three: 'three.js', astro: 'Astro', hono: 'Hono',
};
const PY_FRAMEWORKS: Record<string, string> = { django: 'Django', flask: 'Flask', fastapi: 'FastAPI', pytest: 'pytest', numpy: 'NumPy', pandas: 'pandas', torch: 'PyTorch', tensorflow: 'TensorFlow', sqlalchemy: 'SQLAlchemy', pydantic: 'Pydantic', streamlit: 'Streamlit', typer: 'Typer', click: 'Click' };

export async function detectProject(root: string, index: ProjectIndex): Promise<ProjectProfile> {
  await index.ensure();
  const files = index.list();
  const langCount = new Map<string, number>();
  for (const f of files) if (!['other', 'json', 'yaml', 'markdown', 'toml', 'xml'].includes(f.lang)) langCount.set(f.lang, (langCount.get(f.lang) ?? 0) + 1);
  const languages = [...langCount].sort((a, b) => b[1] - a[1]).map(([lang, n]) => ({ lang, files: n }));

  const rootEntries = await fs.readdir(root).catch(() => [] as string[]);
  const manifests = rootEntries.filter((e) => MANIFESTS.some((m) => (m.startsWith('*') ? e.endsWith(m.slice(1)) : e === m)));
  const frameworks = new Set<string>();
  const entryPoints = new Set<string>();
  const commands: ProjectProfile['commands'] = {};
  let packageManager: string | undefined;

  if (manifests.includes('package.json')) {
    const pkg = await readJson<any>(path.join(root, 'package.json'), {});
    const deps = { ...(pkg.dependencies ?? {}), ...(pkg.devDependencies ?? {}) };
    for (const [k, v] of Object.entries(JS_FRAMEWORKS)) if (deps[k]) frameworks.add(v);
    packageManager = rootEntries.includes('pnpm-lock.yaml') ? 'pnpm' : rootEntries.includes('yarn.lock') ? 'yarn' : rootEntries.includes('bun.lockb') || rootEntries.includes('bun.lock') ? 'bun' : 'npm';
    const run = (s: string) => (packageManager === 'npm' ? `npm run ${s}` : `${packageManager} ${s}`);
    const scripts = pkg.scripts ?? {};
    if (scripts.test && !/no test specified/.test(scripts.test)) commands.test = packageManager === 'npm' ? 'npm test' : `${packageManager} test`;
    if (scripts.build) commands.build = run('build');
    if (scripts.lint) commands.lint = run('lint');
    if (scripts.format) commands.format = run('format');
    if (scripts.typecheck) commands.typecheck = run('typecheck');
    else if (deps.typescript && (await exists(path.join(root, 'tsconfig.json')))) commands.typecheck = 'npx tsc --noEmit';
    if (scripts.dev) commands.run = run('dev');
    else if (scripts.start) commands.run = run('start');
    if (pkg.main) entryPoints.add(pkg.main);
    if (typeof pkg.bin === 'string') entryPoints.add(pkg.bin);
    else if (pkg.bin) for (const v of Object.values(pkg.bin)) entryPoints.add(String(v));
  }
  const pyText = (await fs.readFile(path.join(root, 'pyproject.toml'), 'utf8').catch(() => '')) + (await fs.readFile(path.join(root, 'requirements.txt'), 'utf8').catch(() => ''));
  if (pyText) {
    for (const [k, v] of Object.entries(PY_FRAMEWORKS)) if (new RegExp(`(^|[\\s"'\\[])${k}([\\s<>=~!\\[;"',]|$)`, 'im').test(pyText)) frameworks.add(v);
    if (/pytest/.test(pyText) || files.some((f) => /(^|\/)test_[^/]+\.py$/.test(f.rel))) commands.test ??= 'python -m pytest';
    if (/ruff/.test(pyText)) {
      commands.lint ??= 'ruff check .';
      commands.format ??= 'ruff format .';
    }
    if (/mypy/.test(pyText)) commands.typecheck ??= 'mypy .';
  } else if (languages[0]?.lang === 'python') {
    if (files.some((f) => /(^|\/)test_[^/]+\.py$|_test\.py$/.test(f.rel))) commands.test ??= 'python -m pytest';
  }
  if (manifests.includes('go.mod')) {
    commands.test ??= 'go test ./...';
    commands.build ??= 'go build ./...';
    commands.lint ??= 'go vet ./...';
    commands.format ??= 'gofmt -l -w .';
  }
  if (manifests.includes('Cargo.toml')) {
    commands.test ??= 'cargo test';
    commands.build ??= 'cargo build';
    commands.lint ??= 'cargo clippy';
    commands.format ??= 'cargo fmt';
  }
  if (manifests.includes('pom.xml')) commands.test ??= 'mvn test';
  if (manifests.some((m) => m.startsWith('build.gradle'))) commands.test ??= rootEntries.includes('gradlew') ? './gradlew test' : 'gradle test';
  if (manifests.some((m) => m.endsWith('.csproj') || m.endsWith('.sln'))) {
    commands.test ??= 'dotnet test';
    commands.build ??= 'dotnet build';
  }
  if (manifests.includes('Makefile') && !commands.build) commands.build = 'make';

  const ENTRY = /^(src\/)?(index|main|app|server|cli|manage|__main__)\.(ts|tsx|js|mjs|py|go|rs)$|^cmd\/[^/]+\/main\.go$|^src\/main\.rs$|^src\/lib\.rs$|^main\.py$|^app\.py$/;
  for (const f of files) if (ENTRY.test(f.rel)) entryPoints.add(f.rel);
  if (files.some((f) => /(^|\/)(main|app)\.py$/.test(f.rel)) && !commands.run) {
    const m = files.find((f) => /^(main|app)\.py$/.test(f.rel));
    if (m) commands.run = `python ${m.rel}`;
  }
  const testDirs = [...new Set(files.filter((f) => /(^|\/)(tests?|__tests__|spec)\//.test(f.rel)).map((f) => f.rel.split('/').slice(0, f.rel.split('/').findIndex((s) => /^(tests?|__tests__|spec)$/.test(s)) + 1).join('/')))].slice(0, 10);
  const readmeName = rootEntries.find((e) => /^readme(\.md|\.rst|\.txt)?$/i.test(e));
  const readme = readmeName ? (await fs.readFile(path.join(root, readmeName), 'utf8').catch(() => '')).slice(0, 1500) : undefined;
  const topDirs = rootEntries.filter((e) => files.some((f) => f.rel.startsWith(e + '/'))).slice(0, 30);

  return {
    root,
    name: path.basename(root),
    languages,
    manifests,
    frameworks: [...frameworks],
    packageManager,
    entryPoints: [...entryPoints].slice(0, 15),
    testDirs,
    commands,
    readme,
    isGit: await exists(path.join(root, '.git')),
    fileCount: files.length,
    topDirs,
  };
}

/** Compact codebase map injected into the system prompt (kept small on purpose). */
export function profileSummary(p: ProjectProfile): string {
  const lines: string[] = [];
  lines.push(`Project: ${p.name} (${p.fileCount} indexed files${p.isGit ? ', git repository' : ', not a git repository'})`);
  if (p.languages.length) lines.push(`Languages: ${p.languages.slice(0, 6).map((l) => `${l.lang} (${l.files})`).join(', ')}`);
  if (p.frameworks.length) lines.push(`Frameworks/tools: ${p.frameworks.join(', ')}`);
  if (p.manifests.length) lines.push(`Manifests: ${p.manifests.join(', ')}`);
  if (p.entryPoints.length) lines.push(`Entry points: ${p.entryPoints.join(', ')}`);
  if (p.topDirs.length) lines.push(`Top-level dirs: ${p.topDirs.join(', ')}`);
  if (p.testDirs.length) lines.push(`Tests: ${p.testDirs.join(', ')}`);
  const cmds = Object.entries(p.commands).filter(([, v]) => v);
  if (cmds.length) lines.push(`Commands: ${cmds.map(([k, v]) => `${k}=\`${v}\``).join(', ')}`);
  return lines.join('\n');
}
