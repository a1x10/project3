import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stellaHome } from '../config/paths.js';
import { tokenize } from '../context/index.js';
import { parseFrontmatter, toList } from '../utils/frontmatter.js';

export type SkillScope = 'builtin' | 'user' | 'project' | 'plugin';

export interface Skill {
  name: string;
  description: string;
  whenToUse?: string;
  allowedTools?: string[];
  /** If false, only the user can invoke it (/name); the model is not told about it. */
  modelInvocable: boolean;
  userInvocable: boolean;
  scope: SkillScope;
  dir: string;
  file: string;
  body: string;
}

export interface CustomCommand {
  name: string;
  description: string;
  argumentHint?: string;
  body: string;
  file: string;
  scope: SkillScope;
  model?: string;
  allowedTools?: string[];
}

export function builtinDir(sub: string): string {
  // dist/skills/registry.js or src/skills/registry.ts → <pkg>/builtin/<sub>
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'builtin', sub);
}

/** Loads SKILL.md-based skills and Markdown slash commands from builtin/user/project/plugin dirs. */
export class SkillRegistry {
  private skills = new Map<string, Skill>();
  private commands = new Map<string, CustomCommand>();
  readonly errors: string[] = [];

  constructor(
    private readonly root: string,
    private readonly extraDirs: Array<{ dir: string; scope: SkillScope; kind: 'skills' | 'commands' }> = [],
  ) {}

  dirs(kind: 'skills' | 'commands'): Array<{ dir: string; scope: SkillScope }> {
    return [
      { dir: builtinDir(kind), scope: 'builtin' as SkillScope },
      { dir: path.join(stellaHome(), kind), scope: 'user' as SkillScope },
      ...this.extraDirs.filter((d) => d.kind === kind),
      { dir: path.join(this.root, '.stella', kind), scope: 'project' as SkillScope },
    ];
  }

  async load(): Promise<void> {
    this.skills.clear();
    this.commands.clear();
    for (const { dir, scope } of this.dirs('skills')) {
      let entries: string[] = [];
      try {
        entries = await fs.readdir(dir);
      } catch {
        continue;
      }
      for (const e of entries) {
        const file = path.join(dir, e, 'SKILL.md');
        try {
          const raw = await fs.readFile(file, 'utf8');
          const { data, body } = parseFrontmatter<Record<string, unknown>>(raw);
          const name = String(data.name ?? e).trim();
          if (!/^[a-z0-9][a-z0-9_:-]*$/i.test(name)) {
            this.errors.push(`${file}: invalid skill name "${name}"`);
            continue;
          }
          this.skills.set(name, {
            name,
            description: String(data.description ?? body.split('\n').find((l) => l.trim()) ?? '').slice(0, 500),
            whenToUse: data.when_to_use ? String(data.when_to_use) : undefined,
            allowedTools: toList(data['allowed-tools'] ?? data.allowed_tools),
            modelInvocable: data['disable-model-invocation'] !== true,
            userInvocable: data['user-invocable'] !== false,
            scope,
            dir: path.join(dir, e),
            file,
            body,
          });
        } catch {
          /* not a skill dir */
        }
      }
    }
    for (const { dir, scope } of this.dirs('commands')) {
      let entries: string[] = [];
      try {
        entries = await fs.readdir(dir);
      } catch {
        continue;
      }
      for (const e of entries.filter((x) => x.endsWith('.md'))) {
        const file = path.join(dir, e);
        const raw = await fs.readFile(file, 'utf8').catch(() => '');
        const { data, body } = parseFrontmatter<Record<string, unknown>>(raw);
        const name = e.replace(/\.md$/, '');
        this.commands.set(name, {
          name,
          description: String(data.description ?? body.split('\n').find((l) => l.trim()) ?? '').slice(0, 200),
          argumentHint: data['argument-hint'] ? String(data['argument-hint']) : undefined,
          body,
          file,
          scope,
          model: data.model ? String(data.model) : undefined,
          allowedTools: toList(data['allowed-tools']),
        });
      }
    }
  }

  list(): Skill[] {
    return [...this.skills.values()].sort((a, b) => a.name.localeCompare(b.name));
  }
  get(name: string): Skill | undefined {
    return this.skills.get(name);
  }
  listCommands(): CustomCommand[] {
    return [...this.commands.values()].sort((a, b) => a.name.localeCompare(b.name));
  }
  getCommand(name: string): CustomCommand | undefined {
    return this.commands.get(name);
  }

  /** Prompt listing for the model (only model-invocable skills). */
  promptBlock(): string {
    const xs = this.list().filter((s) => s.modelInvocable);
    if (!xs.length) return '';
    return xs.map((s) => `- ${s.name}: ${s.description}${s.whenToUse ? ` (use when: ${s.whenToUse})` : ''}`).join('\n');
  }

  /** Keyword relevance to surface a likely skill for a prompt. */
  suggest(prompt: string, min = 0.34): Skill | null {
    const q = new Set(tokenize(prompt));
    if (!q.size) return null;
    let best: { s: Skill; score: number } | null = null;
    for (const s of this.list().filter((x) => x.modelInvocable)) {
      const t = new Set(tokenize(`${s.name.replace(/[-_]/g, ' ')} ${s.description} ${s.whenToUse ?? ''}`));
      let hit = 0;
      for (const w of q) if (t.has(w)) hit++;
      const score = hit / Math.min(q.size, 6);
      if (hit >= 2 && score >= min && (!best || score > best.score)) best = { s, score };
    }
    return best?.s ?? null;
  }

  /** Render the skill for the model: body + resource listing. */
  async render(skill: Skill, args?: string): Promise<string> {
    const resources: string[] = [];
    for (const sub of ['references', 'scripts', 'assets', 'templates']) {
      try {
        const files = await fs.readdir(path.join(skill.dir, sub));
        for (const f of files) resources.push(`${sub}/${f}`);
      } catch {
        /* none */
      }
    }
    let body = skill.body.replace(/\$ARGUMENTS/g, args ?? '');
    body = body.replace(/\$\{SKILL_DIR\}/g, skill.dir);
    return [
      `<skill name="${skill.name}" base_dir="${skill.dir}">`,
      body.trim(),
      resources.length ? `\nBundled resources (read with the Read tool, paths relative to base_dir):\n${resources.map((r) => '- ' + r).join('\n')}` : '',
      args ? `\nArguments: ${args}` : '',
      '</skill>',
    ].join('\n');
  }

  async create(scope: 'user' | 'project', name: string, description: string, body = ''): Promise<string> {
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(name)) throw new Error('Skill names must be lowercase letters, digits, - or _');
    const base = scope === 'user' ? path.join(stellaHome(), 'skills') : path.join(this.root, '.stella', 'skills');
    const dir = path.join(base, name);
    await fs.mkdir(path.join(dir, 'references'), { recursive: true });
    await fs.mkdir(path.join(dir, 'scripts'), { recursive: true });
    const file = path.join(dir, 'SKILL.md');
    const content = `---\nname: ${name}\ndescription: ${description.replace(/\n/g, ' ')}\n---\n\n${body || `# ${name}\n\nInstructions for this skill.\n`}`;
    await fs.writeFile(file, content, { flag: 'wx' });
    await this.load();
    return file;
  }

  async remove(name: string): Promise<boolean> {
    const s = this.skills.get(name);
    if (!s || s.scope === 'builtin' || s.scope === 'plugin') return false;
    await fs.rm(s.dir, { recursive: true, force: true });
    await this.load();
    return true;
  }
}
