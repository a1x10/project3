import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { Watchdog } from '../src/watchdog.js';

describe('сторож', () => {
  const make = () => {
    const alerts = [];
    const wa = { isOpen: false, status: 'closed', reconnects: 0, reconnect() { this.reconnects += 1; } };
    const scheduler = { busy: false, busySince: 0 };
    const core = { notifyAdmins: (key, text) => alerts.push({ key, text }) };
    const logger = { warn() {}, error() {}, info() {} };
    return { wa, scheduler, alerts, dog: new Watchdog({ wa, scheduler, core, logger }) };
  };

  it('WhatsApp долго без связи — переподключает сам, потом сообщает о восстановлении', () => {
    const { wa, alerts, dog } = make();
    const t0 = 1_000_000;
    dog.checkWhatsApp(t0);
    dog.checkWhatsApp(t0 + 4 * 60000);
    assert.equal(wa.reconnects, 0, 'короткий обрыв — ждём автопереподключения');
    dog.checkWhatsApp(t0 + 6 * 60000);
    assert.equal(wa.reconnects, 1);
    dog.checkWhatsApp(t0 + 7 * 60000);
    assert.equal(wa.reconnects, 1, 'не чаще раза в 5 минут');
    dog.checkWhatsApp(t0 + 16 * 60000);
    assert.ok(alerts.some((a) => a.key === 'wa-down'));
    wa.isOpen = true;
    dog.checkWhatsApp(t0 + 20 * 60000);
    assert.match(alerts.at(-1).text, /снова на связи \(не было 20 мин\)/);
  });

  it('ожидание привязки по QR — не поломка', () => {
    const { wa, dog } = make();
    wa.status = 'qr';
    dog.checkWhatsApp(0);
    dog.checkWhatsApp(30 * 60000);
    assert.equal(wa.reconnects, 0);
  });

  it('зависший планировщик разблокируется', () => {
    const { scheduler, dog } = make();
    scheduler.busy = true;
    scheduler.busySince = 1000;
    dog.checkScheduler(5 * 60000);
    assert.equal(scheduler.busy, true, 'долгая рассылка — ещё не зависание');
    dog.checkScheduler(12 * 60000);
    assert.equal(scheduler.busy, false);
  });
});
