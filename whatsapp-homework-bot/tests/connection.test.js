import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { Store } from '../src/store.js';
import { WhatsAppConnection } from '../src/whatsapp/connection.js';
import { testConfig } from './helpers.js';

const logger = { info() {}, warn() {}, error() {}, debug() {}, child() { return this; } };

describe('очередь отправки WhatsApp', () => {
  it('фото и текст из рассылки переживают перезапуск и отправляются после подключения', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hwbot-wa-'));
    const config = testConfig({ DATA_DIR: dir, SEND_DELAY_MS: '300' });
    const statePath = path.join(dir, 'state.json');

    // 1) бот поставил рассылку в очередь, но WhatsApp не на связи — и бот перезапустился
    const store1 = new Store(statePath).load();
    const wa1 = new WhatsAppConnection({ config, store: store1, logger });
    fs.mkdirSync(wa1.outboxDir, { recursive: true });
    const photo = Buffer.from([0xff, 0xd8, 0xff, 0x01, 0x02]);
    wa1.send('g@g.us', { image: photo, caption: '📚 Домашнее задание на завтра', mimetype: 'image/jpeg' }, {}, { persist: true });
    wa1.send('g@g.us', { text: 'привет' }, {}, { persist: true });
    store1.save();
    assert.equal(store1.data.outbox.length, 2);
    const photoFile = store1.data.outbox[0].imageFile;
    assert.ok(fs.existsSync(photoFile));
    fs.writeFileSync(path.join(wa1.outboxDir, 'orphan.jpg'), 'x');

    // 2) после перезапуска очередь восстановлена, лишние файлы удалены
    const store2 = new Store(statePath).load();
    const wa2 = new WhatsAppConnection({ config, store: store2, logger });
    wa2.restoreOutbox();
    assert.equal(wa2.queue.length, 2);
    assert.deepEqual(wa2.queue[0].content.image, photo);
    assert.equal(wa2.queue[0].content.caption, '📚 Домашнее задание на завтра');
    assert.equal(wa2.queue[1].content.text, 'привет');
    assert.ok(!fs.existsSync(path.join(wa2.outboxDir, 'orphan.jpg')));

    // 3) WhatsApp подключился — всё отправлено, очередь и файлы очищены
    const sent = [];
    wa2.sock = { sendMessage: async (jid, content) => { sent.push(content); return { key: { id: `S${sent.length}` }, message: {} }; } };
    wa2.status = 'open';
    await wa2.pump();
    assert.equal(sent.length, 2);
    assert.deepEqual(sent[0].image, photo);
    assert.equal(store2.data.outbox.length, 0);
    assert.ok(!fs.existsSync(photoFile));
  });
});
