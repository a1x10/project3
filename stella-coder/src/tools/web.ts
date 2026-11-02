import { z } from 'zod';
import { truncate } from '../utils/fsutil.js';
import { defineTool, ToolError } from './types.js';

const MAX_BYTES = 3_000_000;

export function htmlToText(html: string): string {
  let s = html.replace(/<!--[\s\S]*?-->/g, '');
  s = s.replace(/<(script|style|noscript|svg|iframe|template)[\s\S]*?<\/\1>/gi, '');
  const title = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(s)?.[1]?.trim();
  s = s.replace(/<head[\s\S]*?<\/head>/i, '');
  s = s.replace(/<a\s[^>]*href=["']([^"'#][^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi, (_m, href, text) => {
    const t = text.replace(/<[^>]+>/g, '').trim();
    return t ? `[${t}](${href})` : '';
  });
  s = s.replace(/<h([1-6])[^>]*>([\s\S]*?)<\/h\1>/gi, (_m, n, t) => `\n\n${'#'.repeat(Number(n))} ${t.replace(/<[^>]+>/g, '').trim()}\n\n`);
  s = s.replace(/<li[^>]*>/gi, '\n- ').replace(/<(br|hr)\s*\/?>/gi, '\n');
  s = s.replace(/<pre[^>]*>([\s\S]*?)<\/pre>/gi, (_m, t) => '\n```\n' + t.replace(/<[^>]+>/g, '') + '\n```\n');
  s = s.replace(/<code[^>]*>([\s\S]*?)<\/code>/gi, (_m, t) => '`' + t.replace(/<[^>]+>/g, '') + '`');
  s = s.replace(/<\/(p|div|section|article|tr|table|ul|ol|blockquote|header|footer|main|nav)>/gi, '\n\n');
  s = s.replace(/<[^>]+>/g, '');
  s = decodeEntities(s);
  s = s.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').replace(/[ \t]{2,}/g, ' ');
  return (title ? `# ${decodeEntities(title)}\n\n` : '') + s.trim();
}

function decodeEntities(s: string): string {
  const map: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', mdash: '—', ndash: '–', hellip: '…', copy: '©', laquo: '«', raquo: '»' };
  return s.replace(/&(#x?[0-9a-f]+|\w+);/gi, (m, e: string) => {
    if (e[0] === '#') {
      const code = e[1]?.toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return map[e.toLowerCase()] ?? m;
  });
}

async function fetchText(url: string, signal: AbortSignal, timeoutMs = 30_000): Promise<{ status: number; type: string; text: string; finalUrl: string }> {
  const ctl = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]);
  const res = await fetch(url, { signal: ctl, redirect: 'follow', headers: { 'user-agent': 'Mozilla/5.0 (compatible; StellaCoder/0.1; +https://github.com)', accept: 'text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.5' } });
  const reader = res.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_BYTES) {
        await reader.cancel();
        break;
      }
      chunks.push(value);
    }
  }
  const text = new TextDecoder().decode(Buffer.concat(chunks));
  return { status: res.status, type: res.headers.get('content-type') ?? '', text, finalUrl: res.url };
}

export const WebFetchTool = defineTool({
  name: 'WebFetch',
  description: 'Fetch a URL and return its content as readable text/markdown (HTML is converted; JSON and text returned as-is). Use for documentation, issues, API references. Max ~3MB, output truncated to 40k chars.',
  kind: 'network',
  concurrencySafe: true,
  schema: z.object({ url: z.string().url(), max_chars: z.number().int().min(1000).max(200_000).optional() }),
  describe: (i) => {
    let domain = '';
    try {
      domain = new URL(i.url).hostname;
    } catch {
      /* invalid */
    }
    return { kind: 'network', risk: 'low', readOnly: true, domain, summary: `Fetch ${i.url}` };
  },
  async run(i, ctx) {
    const u = new URL(i.url);
    if (!['http:', 'https:'].includes(u.protocol)) throw new ToolError('Only http(s) URLs are supported');
    if (u.protocol === 'http:' && !/^(localhost|127\.|\[::1\])/.test(u.hostname)) u.protocol = 'https:';
    const r = await fetchText(u.toString(), ctx.signal).catch((e) => {
      throw new ToolError(`Fetch failed: ${(e as Error).message}`);
    });
    const body = /html/i.test(r.type) || /^\s*<!doctype html|^\s*<html/i.test(r.text) ? htmlToText(r.text) : r.text;
    const header = `URL: ${r.finalUrl}\nStatus: ${r.status}\nContent-Type: ${r.type}\n\n`;
    return { content: header + truncate(body, i.max_chars ?? 40_000), isError: r.status >= 400 };
  },
});

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

export function parseDuckDuckGo(html: string): SearchResult[] {
  const out: SearchResult[] = [];
  const re = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?(?:<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>)?/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) && out.length < 20) {
    let url = m[1]!;
    const uddg = /[?&]uddg=([^&]+)/.exec(url);
    if (uddg) url = decodeURIComponent(uddg[1]!);
    if (url.startsWith('//')) url = 'https:' + url;
    out.push({ title: htmlToText(m[2]!).trim(), url, snippet: htmlToText(m[3] ?? '').trim() });
  }
  return out;
}

export const WebSearchTool = defineTool({
  name: 'WebSearch',
  description: 'Search the web and return titles, URLs and snippets. Provider: DuckDuckGo by default, or Brave/Tavily when configured (settings.webSearch). Use WebFetch to read a result.',
  kind: 'network',
  concurrencySafe: true,
  schema: z.object({ query: z.string().min(2), limit: z.number().int().min(1).max(20).optional() }),
  describe: (i) => ({ kind: 'network', risk: 'low', readOnly: true, domain: 'search', summary: `Web search: ${i.query}` }),
  async run(i, ctx) {
    const cfg = ctx.services.settings?.webSearch ?? { provider: 'duckduckgo' };
    const limit = i.limit ?? 8;
    let results: SearchResult[] = [];
    const key = cfg.apiKeyEnv ? process.env[cfg.apiKeyEnv] : undefined;
    try {
      if (cfg.provider === 'brave') {
        if (!key) throw new ToolError(`Set ${cfg.apiKeyEnv ?? 'BRAVE_API_KEY'} for Brave search`);
        const res = await fetch(`https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(i.query)}&count=${limit}`, { headers: { 'X-Subscription-Token': key, accept: 'application/json' }, signal: ctx.signal });
        const j: any = await res.json();
        results = (j.web?.results ?? []).map((r: any) => ({ title: r.title, url: r.url, snippet: htmlToText(r.description ?? '') }));
      } else if (cfg.provider === 'tavily') {
        if (!key) throw new ToolError(`Set ${cfg.apiKeyEnv ?? 'TAVILY_API_KEY'} for Tavily search`);
        const res = await fetch('https://api.tavily.com/search', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ api_key: key, query: i.query, max_results: limit }), signal: ctx.signal });
        const j: any = await res.json();
        results = (j.results ?? []).map((r: any) => ({ title: r.title, url: r.url, snippet: r.content }));
      } else {
        const r = await fetchText(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(i.query)}`, ctx.signal);
        results = parseDuckDuckGo(r.text);
      }
    } catch (e) {
      if (e instanceof ToolError) throw e;
      throw new ToolError(`Search failed: ${(e as Error).message}`);
    }
    if (!results.length) return { content: 'No results.' };
    return { content: results.slice(0, limit).map((r, k) => `${k + 1}. ${r.title}\n   ${r.url}\n   ${r.snippet}`).join('\n') };
  },
});

export const webTools = [WebFetchTool, WebSearchTool];
