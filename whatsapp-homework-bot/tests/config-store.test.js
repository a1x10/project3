import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { buildConfig, ConfigError, validateForStart } from '../src/config.js';
import { Store } from '../src/store.js';

describe('настройки', () => {
  it('значения по умолчанию', () => {
    const c = buildConfig({ GROQ_API_KEY: 'k' });
    assert.equal(c.timezone, 'Asia/Almaty');
    assert.equal(c.schedule.digestTime, 18 * 60);
    assert.equal(c.schedule.morningTime, null);
    assert.equal(c.ai.mode, 'smart');
    assert.equal(c.groq.model, 'openai/gpt-oss-120b');
    assert.equal(c.features.homeworkAttachedTo, 'due');
  });

  it('без ключа Groq ИИ выключается', () => {
    assert.equal(buildConfig({}).ai.mode, 'off');
  });

  it('номера телефонов нормализуются', () => {
    const c = buildConfig({ ADMIN_NUMBERS: '+7 (701) 111-22-33, 87012223344', WA_PAIRING_NUMBER: '+7 700 000 00 00' });
    assert.deepEqual(c.whatsapp.admins, ['77011112233', '77012223344']);
    assert.equal(c.whatsapp.pairingNumber, '77000000000');
  });

  it('понятные ошибки в неверных значениях', () => {
    assert.throws(() => buildConfig({ DIGEST_TIME: '25:00' }), ConfigError);
    assert.throws(() => buildConfig({ AI_MODE: 'always' }), /AI_MODE/);
    assert.throws(() => buildConfig({ BOT_TIMEZONE: 'Mars/Base' }), /BOT_TIMEZONE/);
    assert.throws(() => buildConfig({ POLL_INTERVAL_MINUTES: '1' }), /POLL_INTERVAL_MINUTES/);
    assert.throws(() => buildConfig({ SEND_FILES: 'может быть' }), /SEND_FILES/);
  });

  it('проверка перед запуском', () => {
    const { fatal, warnings } = validateForStart(buildConfig({}));
    assert.equal(fatal.length, 1);
    assert.ok(warnings.some((w) => w.includes('GROQ_API_KEY')));
    assert.equal(validateForStart(buildConfig({ BILIM_LOGIN: 'a', BILIM_PASSWORD: 'b' })).fatal.length, 0);
  });
});

describe('хранилище', () => {
  const tmp = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hwbot-')), 'state.json');

  it('сохраняет и загружает состояние', () => {
    const file = tmp();
    const a = new Store(file).load();
    a.update((s) => { s.groups.g = { name: 'Класс' }; });
    a.save();
    const b = new Store(file).load();
    assert.equal(b.data.groups.g.name, 'Класс');
    assert.ok(!fs.existsSync(`${file}.tmp`));
  });

  it('повреждённый файл не роняет бота', () => {
    const file = tmp();
    fs.writeFileSync(file, '{ это не json');
    const warnings = [];
    const store = new Store(file, { warn: (...args) => warnings.push(args) }).load();
    assert.deepEqual(store.data.groups, {});
    assert.equal(warnings.length, 1);
    assert.ok(fs.readdirSync(path.dirname(file)).some((f) => f.includes('corrupt')));
  });

  it('чистит старые данные', () => {
    const store = new Store(tmp());
    store.data.snapshots['2025-01-01'] = {};
    store.data.snapshots['2025-10-10'] = {};
    store.data.manual.push({ id: 1, date: '2025-01-01' }, { id: 2, date: '2025-10-20' });
    store.data.outbox.push({ id: 'old', createdAt: Date.now() - 5 * 86400000 });
    store.prune('2025-10-14');
    assert.deepEqual(Object.keys(store.data.snapshots), ['2025-10-10']);
    assert.deepEqual(store.data.manual.map((m) => m.id), [2]);
    assert.equal(store.data.outbox.length, 0);
    store.save();
  });
});
