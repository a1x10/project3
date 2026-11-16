// Журнал «что бот понял»: последние решения по сообщениям чата — для панели (почему ответила или промолчала).
import { EventEmitter } from 'node:events';

export class UnderstandJournal extends EventEmitter {
  constructor(size = 300) {
    super();
    this.size = size;
    this.items = [];
    this.seq = 0;
  }

  add(entry) {
    const item = { id: ++this.seq, at: Date.now(), ...entry };
    this.items.push(item);
    if (this.items.length > this.size) this.items.splice(0, this.items.length - this.size);
    this.emit('entry', item);
    return item;
  }

  recent(limit = 100) {
    return this.items.slice(-limit).reverse();
  }

  // Сводка за сегодня: сколько раз что сделала
  summary(since = Date.now() - 24 * 3600 * 1000) {
    const counts = {};
    for (const item of this.items) {
      if (item.at < since) continue;
      counts[item.done || 'другое'] = (counts[item.done || 'другое'] || 0) + 1;
    }
    return counts;
  }
}
