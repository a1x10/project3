import os from 'node:os';
import path from 'node:path';
import { existsSync } from 'node:fs';
import { shortHash } from '../utils/ids.js';

export function stellaHome(): string {
  return process.env.STELLA_HOME ? path.resolve(process.env.STELLA_HOME) : path.join(os.homedir(), '.stella');
}

/** Walk up from `start` looking for a project marker. Falls back to `start`. */
export function findProjectRoot(start: string): string {
  let dir = path.resolve(start);
  const home = os.homedir();
  for (;;) {
    if (existsSync(path.join(dir, '.git')) || existsSync(path.join(dir, 'STELLA.md')) || existsSync(path.join(dir, '.stella'))) {
      if (dir !== home) return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) return path.resolve(start);
    dir = parent;
  }
}

export function projectSlug(root: string): string {
  const base = path.basename(root).replace(/[^A-Za-z0-9_.-]/g, '_') || 'root';
  return `${base}-${shortHash(path.resolve(root).toLowerCase())}`;
}

export interface ProjectPaths {
  root: string;
  dataDir: string; // ~/.stella/projects/<slug>
  sessionsDir: string;
  checkpointsDir: string;
  memoryDir: string;
  indexCache: string;
  auditLog: string;
  projectConfigDir: string; // <root>/.stella
}

export function projectPaths(root: string): ProjectPaths {
  const dataDir = path.join(stellaHome(), 'projects', projectSlug(root));
  return {
    root,
    dataDir,
    sessionsDir: path.join(dataDir, 'sessions'),
    checkpointsDir: path.join(dataDir, 'checkpoints'),
    memoryDir: path.join(dataDir, 'memory'),
    indexCache: path.join(dataDir, 'index.json'),
    auditLog: path.join(dataDir, 'audit.jsonl'),
    projectConfigDir: path.join(root, '.stella'),
  };
}
