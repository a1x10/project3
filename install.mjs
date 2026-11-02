#!/usr/bin/env node
// Installer for STELLA CODER and/or Vibing AI Studio.
// With a Stella Cloud server (--cloud https://ai.example.com) both apps sign in through the
// Telegram bot and use the models of that server; without it STELLA uses a local FreeLLMAPI router.
//
//   node install.mjs                 interactive: choose components, server or local router
//   node install.mjs --stella        only STELLA CODER
//   node install.mjs --studio        only Vibing AI Studio (Windows/desktop app)
//   node install.mjs --cloud <url>   use your Stella Cloud server (no local router needed)
//   node install.mjs --yes           non-interactive, sensible defaults
//   options: --router-mode auto|docker|source|skip  --no-keyless  --email <e> --password <p>
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import * as router from "./tools/freellmapi-router.mjs";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const IS_WIN = process.platform === "win32";
const args = process.argv.slice(2);
const has = (f) => args.includes(f);
const opt = (f) => {
  const i = args.indexOf(f);
  return i >= 0 ? args[i + 1] : undefined;
};
const YES = has("--yes") || has("-y") || !process.stdin.isTTY;

const color = (c) => (s) => (process.stdout.isTTY ? `\x1b[${c}m${s}\x1b[0m` : s);
const violet = color("1;35");
const green = color("1;32");
const yellow = color("1;33");
const red = color("1;31");
const dim = color("2");
const step = (s) => console.log(`\n${violet("✦")} ${s}`);
const ok = (s) => console.log(`  ${green("✔")} ${s}`);
const warn = (s) => console.log(`  ${yellow("!")} ${s}`);
const fail = (s) => console.log(`  ${red("✘")} ${s}`);

let rl = null;
function ask(question, def = "") {
  if (YES) return Promise.resolve(def);
  rl ??= readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((r) => rl.question(`  ${question}${def ? dim(` [${def}]`) : ""}: `, (a) => r(a.trim() || def)));
}

function askHidden(question) {
  if (YES) return Promise.resolve("");
  rl ??= readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    const out = rl.output;
    const write = out.write.bind(out);
    let muted = false;
    out.write = (s, ...rest) => (muted && s !== "\n" && s !== "\r\n" ? true : write(s, ...rest));
    rl.question(`  ${question}: `, (a) => {
      out.write = write;
      write("\n");
      resolve(a.trim());
    });
    muted = true;
  });
}

async function yesNo(q, def = true) {
  const a = (await ask(`${q} ${def ? "(Y/n)" : "(y/N)"}`, "")).toLowerCase();
  return a ? a.startsWith("y") || a.startsWith("д") : def;
}

function npm(argsList, cwd) {
  const bin = IS_WIN ? "npm.cmd" : "npm";
  const r = spawnSync(bin, argsList, { cwd, stdio: "inherit", shell: IS_WIN, env: process.env });
  return r.status === 0;
}

function checkNode() {
  const [maj, min] = process.versions.node.split(".").map(Number);
  if (maj < 20 || (maj === 20 && min < 18)) {
    fail(`Нужен Node.js 20.18 или новее (сейчас ${process.versions.node}). Установите LTS с https://nodejs.org и запустите установщик снова.`);
    process.exitCode = 1;
    throw new Error("unsupported Node.js");
  }
  ok(`Node.js ${process.versions.node}, ${process.platform}/${process.arch}`);
}

// ---------------------------------------------------------------- router

async function setupRouter() {
  let cfg = router.routerConfig();
  step(`Роутер FreeLLMAPI (${cfg.url}, данные в ${cfg.dir})`);
  const mode = opt("--router-mode") || "auto";
  if (mode === "skip") {
    warn("Пропускаю установку роутера (--router-mode skip).");
    return { cfg, running: await router.ping(cfg) };
  }
  console.log(dim("    Проверяю, не запущен ли роутер…"));
  let running = await router.ping(cfg);
  if (running) ok("Роутер уже запущен.");
  else if (await router.portInUse(cfg.port)) warn(`Порт ${cfg.port} занят другой программой (${await router.describePort(cfg.port)}), это не FreeLLMAPI.`);
  else if (router.installedMode(cfg)) {
    const r = await router.ensure(cfg, { log: (m) => console.log(dim(`    ${m}`)) });
    running = r.running;
    running ? ok(`Роутер запущен (${router.installedMode(cfg)}).`) : warn(`Не удалось запустить установленный роутер: ${r.reason}`);
  }
  if (!running) {
    console.log(dim("    Проверяю Docker/Podman (если Docker Desktop только запускается, это может занять до минуты)…"));
    const eng = router.detectEngine();
    console.log(dim(`    Docker/Podman: ${eng ? `${eng.engine}${eng.running ? " (запущен)" : " (не запущен)"}` : "нет"} · Node.js ${process.versions.node}${router.nodeSupportsSource() ? "" : " (для сборки роутера из исходников нужен 20.18–24 — будет использован Docker)"}`));
    try {
      const used = await router.install(cfg, { mode, log: (m) => console.log(dim(`    ${m}`)) });
      running = true;
      cfg = router.routerConfig();
      ok(`Роутер установлен и запущен (${used.mode === "docker" ? "контейнер Docker/Podman" : "из исходников, фоновый процесс"}) — ${used.url}`);
    } catch (e) {
      fail(`Роутер не установлен: ${e.message}`);
      warn("После исправления просто запустите установщик ещё раз — собранное повторно не пересобирается с нуля, а роутер доустановится.");
      warn("Альтернатива для Windows — приложение FreeLLMAPI (.exe): https://github.com/tashfeenahmed/freellmapi/releases/latest, затем: node install.mjs --router-mode skip");
      return { cfg, running: false };
    }
  }
  await connectRouter(cfg);
  return { cfg, running: true };
}

async function connectRouter(cfg) {
  step("Подключение к роутеру (единый ключ freellmapi-…)");
  const existing = router.readRouterKey();
  if (existing && (await router.validateKey(cfg, existing))) {
    ok("Сохранённый ключ работает.");
    return;
  }
  let st;
  try {
    st = await router.dashboardStatus(cfg);
  } catch (e) {
    warn(`Не удалось получить ключ автоматически: ${e.message}`);
    return manualKey(cfg);
  }
  let email = opt("--email");
  let password = opt("--password");
  let generated = false;
  if (st.needsSetup) {
    console.log("  Создаю учётную запись дашборда роутера (она нужна, чтобы управлять ключами провайдеров).");
    email ||= await ask("Email для входа в дашборд", "owner@freellmapi.local");
    if (!password) {
      password = await askHidden("Пароль (не короче 8 символов, Enter — сгенерировать)");
      if (!password) {
        password = randomBytes(12).toString("base64url");
        generated = true;
      }
    }
  } else {
    console.log("  У роутера уже есть учётная запись. Войдите, чтобы получить ключ (Enter — пропустить и вставить ключ вручную).");
    email ||= await ask("Email дашборда", "");
    if (email && !password) password = await askHidden("Пароль");
    if (!email || !password) return manualKey(cfg);
  }
  let token;
  try {
    const c = await router.connect(cfg, { email, password, setupCode: opt("--setup-code") });
    token = c.token;
    if (c.usedSetupCode) ok("Одноразовый код настройки взят из журнала роутера.");
  } catch (e) {
    fail(`Вход не удался: ${e.message}`);
    return manualKey(cfg);
  }
  if (st.needsSetup) {
    let where = "";
    if (generated) {
      // Only a generated password is written down (0600) so the user can log in later.
      const file = path.join(cfg.dir, "dashboard-login.txt");
      fs.writeFileSync(file, `FreeLLMAPI dashboard ${cfg.url}\nemail: ${email}\npassword: ${password}\n`, { mode: 0o600 });
      where = ` (пароль сгенерирован и сохранён в ${file})`;
    }
    ok(`Аккаунт дашборда создан: ${email}${where}`);
  }
  let key;
  try {
    key = await router.getUnifiedKey(cfg, token);
  } catch (e) {
    warn(`Роутер не отдал единый ключ: ${e.message}`);
    return manualKey(cfg);
  }
  router.saveRouterKey(key);
  ok(`Единый ключ получен и сохранён в ${path.join(router.stellaHome(), "credentials.json")} (права 600) — его используют STELLA и студия.`);

  if (!has("--no-keyless")) {
    console.log(`  ${yellow("Важно:")} бесплатные провайдеры без ключа (Kilo Gateway, OVH AI Endpoints) работают сразу, но Kilo по своим правилам`);
    console.log("  может использовать бесплатные запросы для обучения моделей. Не отправляйте через них закрытый код.");
    if (await yesNo("Включить провайдеры без ключа, чтобы роутер работал сразу?", true)) {
      const added = await router.enableKeylessProviders(cfg, token).catch(() => []);
      added.length ? ok(`Включены: ${added.join(", ")}`) : warn("Провайдеры без ключа уже включены или недоступны.");
    }
  }
  if (!YES) {
    console.log("  Добавьте свои бесплатные ключи — они быстрее и надёжнее (Enter — пропустить):");
    for (const [platform, label, hint] of [
      ["groq", "Groq", "https://console.groq.com/keys, ключ gsk_…"],
      ["google", "Google AI Studio (Gemini)", "https://aistudio.google.com/app/apikey, ключ AIza…"],
      ["openrouter", "OpenRouter", "https://openrouter.ai/keys, ключ sk-or-…"],
    ]) {
      const k = await askHidden(`${label} — ${hint}`);
      if (!k) continue;
      try {
        await router.addProviderKey(cfg, token, platform, k);
        ok(`${label}: ключ добавлен`);
      } catch (e) {
        fail(`${label}: ${e.message}`);
      }
    }
  }
  console.log(dim(`    Остальные провайдеры и порядок фолбэка: ${cfg.url} → Keys / Fallback Chain`));
}

async function manualKey(cfg) {
  console.log(`  Откройте ${cfg.url}, страница Keys → скопируйте единый ключ из шапки.`);
  const key = await askHidden("Вставьте ключ freellmapi-… (Enter — позже)");
  if (!key) {
    warn("Ключ не сохранён. Позже: stella auth set freellmapi <ключ> (или node tools/freellmapi-router.mjs key <ключ>).");
    return;
  }
  if (!(await router.validateKey(cfg, key))) warn("Роутер не принял ключ (проверьте его), но он сохранён.");
  router.saveRouterKey(key);
  ok("Ключ сохранён.");
}

// ---------------------------------------------------------------- components

/** All executables named `name` on PATH, in resolution order. */
function findOnPath(name) {
  const exts = IS_WIN ? (process.env.PATHEXT || ".EXE;.CMD;.BAT;.PS1").split(";") : [""];
  const out = [];
  for (const d of (process.env.PATH || "").split(path.delimiter)) {
    if (!d) continue;
    for (const ext of exts) {
      const p = path.join(d, name + ext.toLowerCase());
      const P = path.join(d, name + ext);
      for (const cand of new Set([p, P])) if (fs.existsSync(cand) && !out.some((x) => x.toLowerCase() === cand.toLowerCase())) out.push(cand);
    }
  }
  return out;
}

/** Warn when another program's `stella` command shadows ours (e.g. a Hermes Agent profile alias). */
function checkStellaCommand(dir) {
  const hits = findOnPath("stella");
  if (!hits.length) return;
  let first = "";
  try {
    first = fs.readFileSync(hits[0], "utf8");
  } catch {
    /* binary */
  }
  const ours = first.includes("stella-coder") || first.includes(path.join(dir, "dist")) || first.includes("dist/cli/main.js") || first.includes("dist\\cli\\main.js");
  if (!ours) {
    warn(`Команда stella в PATH принадлежит другой программе: ${hits[0]}`);
    warn("Запускайте STELLA CODER командой stella-coder (она установлена вместе с stella).");
  }
}

function linkStella(dir) {
  if (npm(["link"], dir)) {
    checkStellaCommand(dir);
    return "npm link — команды stella и stella-coder";
  }
  // Global prefix not writable (system Node): drop a launcher into a user bin dir.
  const main = path.join(dir, "dist", "cli", "main.js");
  if (IS_WIN) {
    const bin = path.join(process.env.APPDATA || os.homedir(), "npm");
    fs.mkdirSync(bin, { recursive: true });
    for (const n of ["stella", "stella-coder"]) fs.writeFileSync(path.join(bin, `${n}.cmd`), `@echo off\r\n"${process.execPath}" "${main}" %*\r\n`);
    checkStellaCommand(dir);
    return path.join(bin, "stella-coder.cmd");
  }
  const bin = path.join(os.homedir(), ".local", "bin");
  fs.mkdirSync(bin, { recursive: true });
  for (const n of ["stella", "stella-coder"]) fs.writeFileSync(path.join(bin, n), `#!/bin/sh\nexec "${process.execPath}" "${main}" "$@"\n`, { mode: 0o755 });
  if (!(process.env.PATH || "").split(path.delimiter).includes(bin)) warn(`Добавьте ${bin} в PATH (например, в ~/.bashrc: export PATH="$HOME/.local/bin:$PATH").`);
  checkStellaCommand(dir);
  return path.join(bin, "stella-coder");
}

function installStella() {
  step("STELLA CODER — терминальный агент");
  const dir = path.join(ROOT, "stella-coder");
  if (!npm(["ci", "--no-audit", "--no-fund"], dir) || !npm(["run", "build"], dir)) {
    fail("Не удалось собрать STELLA CODER (см. вывод npm выше).");
    return false;
  }
  ok(`Команда stella установлена (${linkStella(dir)}).`);
  return true;
}

function installStudio() {
  step("Vibing AI Studio — приложение-конструктор сайтов");
  const dir = path.join(ROOT, "vibing-studio");
  if (!npm(["ci", "--no-audit", "--no-fund"], dir) || !npm(["run", "build"], dir)) {
    fail("Не удалось собрать студию (см. вывод npm выше).");
    return false;
  }
  ok("Приложение собрано.");
  return true;
}

/** Stella Cloud server: --cloud, STELLA_CLOUD_URL, a saved one, or ask. Empty = local router only. */
async function setupCloud(needed) {
  let url = opt("--cloud") || router.readCloudUrl();
  if (!url && !YES) {
    step("Сервер Stella Cloud");
    console.log(dim("  Ваш сервер с ботом-регистрацией и моделями (cloud/deploy.sh). Студии он нужен обязательно, STELLA может работать и с локальным роутером."));
    url = await ask(needed ? "Адрес сервера, например https://ai.example.com" : "Адрес сервера (Enter — без него, локальный роутер)", "");
  }
  if (!url) return "";
  url = url.trim().replace(/\/+$/, "").replace(/\/v1$/, "");
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
  try {
    const r = await fetch(`${url}/api/config`, { signal: AbortSignal.timeout(10_000) });
    const j = await r.json();
    ok(`Сервер ${url} отвечает${j.botUsername ? ` · бот @${j.botUsername}` : " · бот не настроен"}`);
  } catch (e) {
    warn(`Сервер ${url} сейчас не отвечает (${e.message}) — адрес всё равно сохранён.`);
  }
  router.saveCloudUrl(url);
  return url;
}

// ---------------------------------------------------------------- main

async function main() {
  if (has("--help-check")) {
    // CI smoke check: modules load and the environment is detected, nothing is installed.
    console.log(JSON.stringify({ node: process.versions.node, engine: router.detectEngine()?.engine ?? null, router: await router.status() }));
    return;
  }
  console.log(violet("\n  ✦ STELLA CODER · Vibing AI Studio — установка\n"));
  checkNode();
  let stella = has("--stella");
  let studio = has("--studio");
  if (!stella && !studio) {
    const choice = await ask("Что установить? 1 — STELLA CODER, 2 — Vibing AI Studio, 3 — оба", "3");
    stella = choice === "1" || choice === "3";
    studio = choice === "2" || choice === "3";
  }
  const cloud = await setupCloud(studio && !stella);
  // the local router is only needed when STELLA works without a server
  const local = !cloud || has("--with-router") ? await setupRouter() : null;
  const results = {};
  if (stella) results.stella = installStella();
  if (studio) results.studio = installStudio();
  rl?.close();

  step("Готово");
  if (cloud) console.log(`  Stella Cloud: ${cloud} — вход через Telegram-бота`);
  if (local) {
    console.log(`  Роутер FreeLLMAPI: ${local.running ? green("работает") : red("не запущен")} — ${local.cfg.url} (дашборд)`);
    console.log(dim("  Роутер запускается автоматически при старте stella; вручную: node tools/freellmapi-router.mjs start|stop|status|logs"));
  }
  if (results.stella) {
    console.log(`\n  ${violet("STELLA CODER")}`);
    if (cloud) console.log(`    stella-coder login    # один раз: подтвердите вход в Telegram — дальше модель cloud:auto`);
    console.log("    cd ваш-проект");
    console.log(`    stella-coder          # интерактивная сессия${cloud ? "" : " (модель freellmapi:auto:smart)"}; то же: stella`);
    console.log('    stella-coder -p "задача"');
  }
  if (results.studio) {
    console.log(`\n  ${violet("Vibing AI Studio")} — приложение`);
    console.log(`    cd "${path.join(ROOT, "vibing-studio")}"`);
    console.log("    npm run desktop       # открыть приложение; вход — кнопкой «Войти через Telegram»");
    if (IS_WIN) console.log("    npm run dist:win      # собрать установщик VibingAIStudio-Setup.exe (папка release)");
    if (!cloud) warn("Студии нужен сервер Stella Cloud — адрес можно ввести в окне входа приложения.");
  }
  if (Object.values(results).some((v) => v === false)) process.exitCode = 1;
}

main()
  .catch((e) => {
    fail(e.stack || e.message);
    process.exitCode = 1;
  })
  .finally(() => {
    rl?.close();
    process.stdin.pause();
  });
