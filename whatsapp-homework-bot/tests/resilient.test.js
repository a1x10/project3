import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { BilimApiError, BilimAuthError } from '../src/bilimclass/client.js';
import { ResilientBilimClient } from '../src/bilimclass/resilient.js';

class FakeApi {
  constructor() {
    this.fail = null;
    this.calls = 0;
    this.session = { className: '7 В' };
  }

  async getWeek(monday) {
    this.calls += 1;
    if (this.fail) throw this.fail;
    return { date: monday, days: [{ via: 'api' }] };
  }
}

class FakeSite {
  constructor() {
    this.available = true;
    this.calls = [];
    this.fail = null;
  }

  async fetchWeeks(mondays) {
    this.calls.push(mondays);
    if (this.fail) throw this.fail;
    return new Map(mondays.map((m) => [m, { date: m, days: [{ via: 'site' }] }]));
  }
}

describe('два способа получить дневник', () => {
  it('обычно — через API', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const client = new ResilientBilimClient({ api, site });
    const week = await client.getWeek('2026-10-12');
    assert.equal(week.days[0].via, 'api');
    assert.equal(site.calls.length, 0);
  });

  it('API сломалось — дневник через сайт, админу одно уведомление, дальше полчаса сразу через сайт', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const switches = [];
    const client = new ResilientBilimClient({ api, site, onSwitch: (mode) => switches.push(mode) });
    api.fail = new BilimApiError('HTTP 426', 426);
    const week = await client.getWeek('2026-10-12');
    assert.equal(week.days[0].via, 'site');
    assert.deepEqual(switches, ['site']);
    await client.getWeek('2026-10-19');
    assert.equal(api.calls, 1, 'второй раз API не дёргаем');
    assert.equal(client.status().mode, 'site');
  });

  it('через полчаса снова пробует API и возвращается на него', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const switches = [];
    const client = new ResilientBilimClient({ api, site, onSwitch: (mode) => switches.push(mode) });
    api.fail = new BilimApiError('down', 500);
    await client.getWeek('2026-10-12');
    client.preferSiteUntil = 0; // прошло полчаса
    api.fail = null;
    const week = await client.getWeek('2026-10-12');
    assert.equal(week.days[0].via, 'api');
    assert.deepEqual(switches, ['site', 'api']);
  });

  it('несколько недель сразу — один заход на сайт', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const client = new ResilientBilimClient({ api, site });
    api.fail = new BilimApiError('down', 500);
    await client.getWeek('2026-10-12');
    site.calls = [];
    const [a, b] = await Promise.all([client.getWeek('2026-10-19'), client.getWeek('2026-10-26')]);
    assert.equal(a.date, '2026-10-19');
    assert.equal(b.date, '2026-10-26');
    assert.deepEqual(site.calls, [['2026-10-19', '2026-10-26']]);
  });

  it('неверный пароль — сайт не пробуем (он тоже не пустит)', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const client = new ResilientBilimClient({ api, site });
    api.fail = new BilimAuthError('Неправильный логин или пароль');
    await assert.rejects(() => client.getWeek('2026-10-12'), BilimAuthError);
    assert.equal(site.calls.length, 0);
  });

  it('не работает ни API, ни сайт — понятная ошибка про оба способа', async () => {
    const api = new FakeApi();
    const site = new FakeSite();
    const client = new ResilientBilimClient({ api, site });
    api.fail = new BilimApiError('HTTP 500', 500);
    site.fail = new Error('timeout');
    await assert.rejects(() => client.getWeek('2026-10-12'), /ни через API \(HTTP 500\), ни через сайт \(timeout\)/);
  });

  it('без браузера — ошибка API как есть', async () => {
    const api = new FakeApi();
    const client = new ResilientBilimClient({ api, site: null });
    api.fail = new BilimApiError('HTTP 500', 500);
    await assert.rejects(() => client.getWeek('2026-10-12'), /HTTP 500/);
  });
});
